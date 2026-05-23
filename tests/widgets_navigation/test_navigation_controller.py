from tests.widgets_navigation._shared import *

@unittest.skipUnless(HAS_QT, "PySide6 is required for widget tests")
class NavigationControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt_app()

    def test_tab_switch_restores_last_album_route(self):
        class FakeSignal:
            def __init__(self):
                self._callbacks = []

            def connect(self, callback):
                self._callbacks.append(callback)

            def emit(self, *args):
                for callback in list(self._callbacks):
                    callback(*args)

        class FakeTabs:
            def __init__(self, widgets):
                self.currentChanged = FakeSignal()
                self._widgets = list(widgets)
                self._current = self._widgets[0]

            def widget(self, idx):
                return self._widgets[idx]

            def setCurrentWidget(self, widget):
                self._current = widget
                self.currentChanged.emit(self._widgets.index(widget))

        class FakeLayout:
            def count(self):
                return 0

            def takeAt(self, _index):
                return None

            def addWidget(self, _widget):
                return None

            def addStretch(self, _stretch):
                return None

        tracks_tab = QWidget()
        albums_page = QWidget()
        artists_page = QWidget()
        tabs = FakeTabs([tracks_tab, albums_page, artists_page])
        apply_route = MagicMock()
        controller = NavigationController(
            db=object(),
            tabs=tabs,
            tracks_tab=tracks_tab,
            albums_page=albums_page,
            artists_page=artists_page,
            breadcrumbs_layout=FakeLayout(),
            apply_route=apply_route,
            display_artist_name=lambda value: value or "",
            display_album_name=lambda value: value or "",
        )
        controller._persist_library_route = MagicMock()
        controller._update_breadcrumbs = MagicMock()

        album_route = albums_detail((11,), label="Kid A")
        controller.navigate_to(album_route)
        apply_route.reset_mock()

        tabs.setCurrentWidget(tracks_tab)
        self.assertEqual(controller.current_route, tracks_all())

        tabs.setCurrentWidget(albums_page)

        self.assertEqual(controller.current_route, album_route)
        self.assertEqual(apply_route.call_args_list, [call(tracks_all()), call(album_route)])
