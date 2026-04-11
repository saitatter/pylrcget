from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from PySide6.QtCore import QObject, QTimer, Qt
from PySide6.QtWidgets import QLabel, QLayout, QTabWidget, QToolButton, QWidget

from db.database import get_album_by_id, get_artist_by_id, get_config, set_config
from ui.library_routes import LibraryRoute, deserialize_route, route_breadcrumbs, serialize_route, tracks_all


ApplyRouteCallback = Callable[[LibraryRoute], None]
DisplayNameCallback = Callable[[str | None], str]


class NavigationController(QObject):
    def __init__(
        self,
        *,
        db,
        tabs: QTabWidget,
        tracks_tab: QWidget,
        albums_page: QWidget,
        artists_page: QWidget,
        breadcrumbs_layout: QLayout,
        apply_route: ApplyRouteCallback,
        display_artist_name: DisplayNameCallback,
        display_album_name: DisplayNameCallback,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._db = db
        self._tabs = tabs
        self._tracks_tab = tracks_tab
        self._albums_page = albums_page
        self._artists_page = artists_page
        self._breadcrumbs_layout = breadcrumbs_layout
        self._apply_route = apply_route
        self._display_artist_name = display_artist_name
        self._display_album_name = display_album_name

        self._nav_history: list[LibraryRoute] = []
        self._nav_index: int = -1
        self._current_route = tracks_all()
        self._artist_label_cache: dict[int, str] = {}
        self._album_label_cache: dict[int, str] = {}
        self._nav_apply_in_progress = False
        self._tab_sync_suppressed = False
        self._pending_library_route: str | None = None

        self._route_save_timer = QTimer(self)
        self._route_save_timer.setSingleShot(True)
        self._route_save_timer.setInterval(250)
        self._route_save_timer.timeout.connect(self.flush_pending_route)

        self._tabs.currentChanged.connect(self.on_tab_changed)

    @property
    def current_route(self) -> LibraryRoute:
        return self._current_route

    def navigate_to(self, route: LibraryRoute, *, record_history: bool = True) -> None:
        route = self._hydrate_route(route)
        self._current_route = route
        self._nav_apply_in_progress = True
        try:
            self._tab_sync_suppressed = True
            self._set_current_tab_for_route(route)
            self._apply_route(route)
        finally:
            self._tab_sync_suppressed = False
            self._nav_apply_in_progress = False

        if record_history:
            if self._nav_index < 0 or self._nav_history[self._nav_index] != route:
                self._nav_history = self._nav_history[: self._nav_index + 1]
                self._nav_history.append(route)
                self._nav_index = len(self._nav_history) - 1
        self._persist_library_route(route)
        self._update_breadcrumbs()

    def restore_last_route(self) -> None:
        config = get_config(self._db)
        route = deserialize_route(config.last_library_route)
        if route is None:
            route = tracks_all()
        self._nav_history = [route]
        self._nav_index = 0
        self.navigate_to(route, record_history=False)

    def flush_pending_route(self) -> None:
        if self._pending_library_route is None:
            return
        config = get_config(self._db)
        set_config(self._db, replace(config, last_library_route=self._pending_library_route))
        self._pending_library_route = None

    def on_tab_changed(self, idx: int) -> None:
        if self._tab_sync_suppressed or self._nav_apply_in_progress:
            return
        current = self._tabs.widget(idx)
        if current is self._tracks_tab:
            self.navigate_to(tracks_all())
        elif current is self._albums_page:
            self.navigate_to(LibraryRoute(tab="albums", mode="root"))
        elif current is self._artists_page:
            self.navigate_to(LibraryRoute(tab="artists", mode="root"))

    def _set_current_tab_for_route(self, route: LibraryRoute) -> None:
        if route.tab == "tracks":
            self._tabs.setCurrentWidget(self._tracks_tab)
        elif route.tab == "albums":
            self._tabs.setCurrentWidget(self._albums_page)
        elif route.tab == "artists":
            self._tabs.setCurrentWidget(self._artists_page)

    def _persist_library_route(self, route: LibraryRoute) -> None:
        self._pending_library_route = serialize_route(route)
        self._route_save_timer.start()

    def _hydrate_route(self, route: LibraryRoute) -> LibraryRoute:
        artist_label = route.artist_label
        album_label = route.album_label

        if not artist_label and len(route.artist_ids) == 1:
            artist_id = int(route.artist_ids[0])
            artist_label = self._artist_label_cache.get(artist_id, artist_label)
            if not artist_label:
                try:
                    artist = get_artist_by_id(self._db, artist_id)
                    artist_label = self._display_artist_name(artist.get("artist_name", ""))
                    if artist_label:
                        self._artist_label_cache[artist_id] = artist_label
                except Exception:
                    pass

        if not album_label and len(route.album_ids) == 1:
            album_id = int(route.album_ids[0])
            album_label = self._album_label_cache.get(album_id, album_label)
            if not album_label:
                try:
                    album = get_album_by_id(self._db, album_id)
                    album_label = self._display_album_name(album.get("album_name", ""))
                    if album_label:
                        self._album_label_cache[album_id] = album_label
                    if not artist_label:
                        artist_label = self._display_artist_name(
                            album.get("artist_name") or album.get("album_artist_name") or ""
                        )
                        artist_id = album.get("artist_id")
                        if artist_label and artist_id is not None:
                            self._artist_label_cache[int(artist_id)] = artist_label
                except Exception:
                    pass

        if artist_label == route.artist_label and album_label == route.album_label:
            return route
        return replace(route, artist_label=artist_label, album_label=album_label)

    def _update_breadcrumbs(self) -> None:
        while self._breadcrumbs_layout.count():
            item = self._breadcrumbs_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        crumbs = route_breadcrumbs(self._current_route)
        for idx, (label, route) in enumerate(crumbs):
            button = QToolButton()
            button.setObjectName("LibraryBreadcrumbButton")
            button.setText(label)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            button.setAutoRaise(True)
            button.setEnabled(idx != len(crumbs) - 1)
            if idx != len(crumbs) - 1:
                button.clicked.connect(lambda _=False, r=route: self.navigate_to(r))
            self._breadcrumbs_layout.addWidget(button)
            if idx != len(crumbs) - 1:
                separator = QLabel(">")
                separator.setObjectName("LibraryBreadcrumbSeparator")
                self._breadcrumbs_layout.addWidget(separator)
        self._breadcrumbs_layout.addStretch(1)
