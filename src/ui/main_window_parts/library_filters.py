from __future__ import annotations


def apply_track_filters(window) -> None:
    filters = window.top_bar.filter_values()
    search_text = window.top_bar.search_text()
    track_lists = [
        window.track_list,
        window.albums_tab.track_list,
        window.artists_tab.album_browser.track_list,
    ]
    if hasattr(window, "album_artists_tab") and hasattr(window.album_artists_tab, "album_browser"):
        track_lists.append(window.album_artists_tab.album_browser.track_list)
    for track_list in track_lists:
        track_list.setSearchValue(search_text)
        track_list.setFilters(
            synced=filters["synced"],
            plain=filters["plain"],
            instrumental=filters["instrumental"],
            none_=filters["none"],
            unsaved=filters.get("unsaved", False),
        )
        if window.app_state.player and window.app_state.player.track:
            track_list.set_now_playing(window.app_state.player.track.track_id)
    window._update_search_feedback()


def schedule_library_search(window) -> None:
    window._search_apply_timer.start()


def apply_library_search(window) -> None:
    current = window.tabs.currentWidget()
    text = window.top_bar.search_text()
    if current is window.tracks_tab:
        window._apply_track_filters()
    elif current is window.albums_page:
        window.albums_tab.setSearchValue(text)
    elif current is window.artists_page:
        window.artists_tab.setSearchValue(text)
    elif current is window.album_artists_page:
        window.album_artists_tab.setSearchValue(text)