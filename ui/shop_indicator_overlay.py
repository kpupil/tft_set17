"""
TFT Assistant — 商店命中提示层
================================
在游戏画面上方绘制一个不抢占鼠标的透明层：
  - 常态监听 AutoPicker 的识别结果
  - 当商店某格命中待拿列表时，在配置好的槽位锚点显示固定图标
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QApplication, QWidget

from bot.region_selector import RegionConfig
from config import ROOT_DIR

ICON_SIZE = 52
ICON_PATH = ROOT_DIR / "assets" / "shop_hint_badge.svg"


class ShopIndicatorOverlay(QWidget):
    """绘制商店命中提示标记的透明悬浮层。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._config: RegionConfig | None = None
        self._matches: list[dict] = []
        self._target_rect = QRect()
        self._slot_points: list[list[int]] = []
        self._badge = self._load_badge(ICON_PATH)
        self._setup_window()

    def _setup_window(self):
        flags = (
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowDoesNotAcceptFocus
        )
        if hasattr(Qt.WindowType, "WindowTransparentForInput"):
            flags |= Qt.WindowType.WindowTransparentForInput

        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()

    @staticmethod
    def _load_badge(path: Path) -> QPixmap:
        renderer = QSvgRenderer(str(path))
        if not renderer.isValid():
            return QPixmap()

        pixmap = QPixmap(ICON_SIZE, ICON_SIZE)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        return pixmap

    def update_region_config(self, config: RegionConfig | None):
        self._config = config
        if not config or not config.is_valid():
            self._slot_points = []
            self._target_rect = QRect()
            self.hide()
            return

        target_rect = config.resolved_screen_rect()
        if not target_rect.isValid():
            target_rect = self._compute_desktop_rect()

        self._target_rect = target_rect
        self._slot_points = config.resolved_slot_points_for_target(target_rect)
        self.setGeometry(target_rect)
        self._sync_visibility()

    def update_matches(self, matches: Iterable[dict]):
        self._matches = list(matches)
        self._sync_visibility()

    def clear_matches(self):
        self.update_matches([])

    def _sync_visibility(self):
        if not self._slot_points or not self._matches or not self._target_rect.isValid():
            self.hide()
            return
        self.show()
        self.raise_()
        self.update()

    @staticmethod
    def _compute_desktop_rect() -> QRect:
        screens = QApplication.screens()
        if not screens:
            return QRect(0, 0, 1920, 1080)
        rect = QRect(screens[0].geometry())
        for screen in screens[1:]:
            rect = rect.united(screen.geometry())
        return rect

    def paintEvent(self, _event):
        if not self._matches or not self._slot_points:
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        for match in self._matches:
            slot_idx = int(match.get("slot_idx", -1))
            if slot_idx < 0 or slot_idx >= len(self._slot_points):
                continue

            point = self._slot_points[slot_idx]
            if len(point) != 2:
                continue

            pt = QPoint(*point) - self._target_rect.topLeft()
            self._draw_marker(p, pt)

        p.end()

    def _draw_marker(self, p: QPainter, pt: QPoint):
        if not self._badge.isNull():
            p.drawPixmap(
                pt.x() - ICON_SIZE // 2,
                pt.y() - ICON_SIZE // 2,
                self._badge,
            )
