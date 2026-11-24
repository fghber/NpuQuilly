"""System tray (PySide6). Imported lazily by application.py."""
from typing import Callable


def _make_icon():
    """Runtime-drawn tray icon (teal disc + white N) — no asset file needed."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
    size = 64
    pm = QPixmap(size, size)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    teal = QColor("#0e7c7b")
    p.setBrush(teal)
    p.setPen(teal)
    p.drawEllipse(2, 2, size - 4, size - 4)
    p.setPen(QColor("white"))
    p.setFont(QFont("Segoe UI", 30, QFont.Bold))
    p.drawText(pm.rect(), Qt.AlignCenter, "N")
    p.end()
    return QIcon(pm)


class TrayManager:
    def __init__(self, app, on_settings: Callable, on_quit: Callable):
        self._app = app
        self._on_settings = on_settings
        self._on_quit = on_quit
        self.tray = None
        # Persistent refs: Qt does NOT take ownership in setContextMenu, so a
        # local QMenu would be GC'd while the tray still points at it
        # (use-after-free crash, e.g. when a dialog opened from the menu closes).
        self._menu = None
        self._actions: dict = {}
        self._paused = False

    def show(self):
        from PySide6.QtWidgets import QSystemTrayIcon, QMenu
        self.tray = QSystemTrayIcon(_make_icon(), self._app)
        self._menu = QMenu()
        menu = self._menu
        self._actions["settings"] = menu.addAction("Settings")
        self._actions["pause"] = menu.addAction("Pause")
        self._actions["quit"] = menu.addAction("Quit")
        self._actions["settings"].triggered.connect(self._on_settings)
        self._actions["quit"].triggered.connect(self._on_quit)

        def toggle():
            self._paused = not self._paused
            self._actions["pause"].setText("Resume" if self._paused else "Pause")
        self._actions["pause"].triggered.connect(toggle)
        self.tray.setContextMenu(menu)
        self.tray.setToolTip("NpuQuilly — local grammar helper")
        self.tray.show()

    @property
    def paused(self) -> bool:
        return self._paused
