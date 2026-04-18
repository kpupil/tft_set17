"""
TFT Assistant — 羁绊展示组件
============================
用于展示紧凑羁绊条。
"""

from __future__ import annotations

from PyQt6.QtCore import QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QWidget

from ui.image_cache import ImageCache

TEXT_GOLD = "#d8b35a"
TEXT_RED = "#d45b66"

CHIP_W = 30
CHIP_H = 26
CHIP_ICON_SZ = 16
EMBLEM_TAG_W = 24
EMBLEM_TAG_H = 24


class CompactTraitChip(QWidget):
    """单行紧凑羁绊条目。"""

    clicked = pyqtSignal(str)

    def __init__(
        self,
        trait_id: str,
        name: str,
        icon: str,
        current_count: int,
        active: bool,
        active_threshold: int = 0,
        is_emblem: bool = False,
        removable: bool = False,
        clickable: bool = False,
        item_key: str | None = None,
        cache: ImageCache | None = None,
        tooltip: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._trait_id = trait_id
        self._item_key = item_key or trait_id
        self._name = name
        self._icon = icon
        self._current_count = current_count
        self._active = active
        self._active_threshold = active_threshold
        self._is_emblem = is_emblem
        self._removable = removable
        self._clickable = clickable
        self._cache = cache or ImageCache.instance()
        self._px: QPixmap | None = self._cache.get(icon) if icon else None

        self.setFixedSize(CHIP_W, CHIP_H)
        self.setCursor(
            Qt.CursorShape.PointingHandCursor if (removable or clickable) else Qt.CursorShape.ArrowCursor
        )
        self.setToolTip(tooltip or name)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._cache.image_ready.connect(self._on_ready)

    def _on_ready(self, icon_path: str, px: QPixmap):
        if icon_path == self._icon:
            self._px = px
            self.update()

    def mousePressEvent(self, e):
        if (self._removable or self._clickable) and e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._item_key)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        bg = QColor("#2a3550") if self._is_emblem else (
            QColor("#203858") if self._active else QColor("#1a2230")
        )
        border = QColor("#8a6a2c") if self._is_emblem else (
            QColor("#4d77a7") if self._active else QColor("#2b374a")
        )
        accent = QColor(TEXT_GOLD) if (self._active or self._is_emblem) else QColor("#6f7d92")

        p.setPen(QPen(border, 1))
        p.setBrush(bg)
        p.drawRoundedRect(1, 1, CHIP_W - 2, CHIP_H - 2, 6, 6)

        icon_x = 7
        icon_y = 6
        clip = QPainterPath()
        clip.addRoundedRect(icon_x, icon_y, CHIP_ICON_SZ, CHIP_ICON_SZ, 5, 5)
        p.setClipPath(clip)
        if self._px:
            src = self._px
            side = min(src.width(), src.height())
            sx = (src.width() - side) // 2
            sy = (src.height() - side) // 2
            p.drawPixmap(
                QRect(icon_x, icon_y, CHIP_ICON_SZ, CHIP_ICON_SZ),
                src,
                QRect(sx, sy, side, side),
            )
        else:
            p.fillRect(icon_x, icon_y, CHIP_ICON_SZ, CHIP_ICON_SZ, QColor("#2a3344"))
        p.setClipping(False)

        p.setPen(QPen(QColor("#4a5b75"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(icon_x, icon_y, CHIP_ICON_SZ, CHIP_ICON_SZ, 5, 5)

        badge_rect = QRect(6, 0, 18, 9)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#102033") if self._active else QColor("#1b2736"))
        p.drawRoundedRect(badge_rect, 5, 5)

        p.setPen(accent)
        count_font = QFont()
        count_font.setPointSize(4)
        count_font.setBold(True)
        p.setFont(count_font)
        display_left = self._active_threshold if self._active_threshold else self._current_count
        display_text = f"{display_left}/{self._current_count}"
        p.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, display_text)

        if self._removable:
            close_rect = QRect(CHIP_W - 9, 1, 8, 8)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(TEXT_RED))
            p.drawEllipse(close_rect)
            p.setPen(QColor("white"))
            x_font = QFont()
            x_font.setPointSize(4)
            x_font.setBold(True)
            p.setFont(x_font)
            p.drawText(close_rect, Qt.AlignmentFlag.AlignCenter, "x")

        p.end()


class SelectedEmblemTag(QWidget):
    """标题行里的已选转职图标。"""

    clicked = pyqtSignal(str)

    def __init__(
        self,
        item_key: str,
        name: str,
        icon: str,
        cache: ImageCache | None = None,
        tooltip: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._item_key = item_key
        self._name = name
        self._icon = icon
        self._cache = cache or ImageCache.instance()
        self._px: QPixmap | None = self._cache.get(icon) if icon else None

        self.setFixedSize(EMBLEM_TAG_W, EMBLEM_TAG_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tooltip or name)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._cache.image_ready.connect(self._on_ready)

    def _on_ready(self, icon_path: str, px: QPixmap):
        if icon_path == self._icon:
            self._px = px
            self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._item_key)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        p.setPen(QPen(QColor("#8a6a2c"), 1))
        p.setBrush(QColor("#2a3550"))
        p.drawRoundedRect(1, 1, EMBLEM_TAG_W - 2, EMBLEM_TAG_H - 2, 6, 6)

        icon_x = 4
        icon_y = 4
        clip = QPainterPath()
        clip.addRoundedRect(icon_x, icon_y, 16, 16, 4, 4)
        p.setClipPath(clip)
        if self._px:
            src = self._px
            side = min(src.width(), src.height())
            sx = (src.width() - side) // 2
            sy = (src.height() - side) // 2
            p.drawPixmap(QRect(icon_x, icon_y, 16, 16), src, QRect(sx, sy, side, side))
        else:
            p.fillRect(icon_x, icon_y, 16, 16, QColor("#2a3344"))
        p.setClipping(False)

        close_rect = QRect(EMBLEM_TAG_W - 10, 1, 8, 8)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(TEXT_RED))
        p.drawEllipse(close_rect)
        p.setPen(QColor("white"))
        x_font = QFont()
        x_font.setPointSize(5)
        x_font.setBold(True)
        p.setFont(x_font)
        p.drawText(close_rect, Qt.AlignmentFlag.AlignCenter, "x")
        p.end()
