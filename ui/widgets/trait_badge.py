"""
TFT Assistant — 羁绊展示组件
============================
两套视觉方案，通过 `CHIP_VARIANT` 顶层常量切换：
  - "A" 图标状态芯片：图标 + 右下数量（34×32，信息密度高）
  - "B" 方形增强：图标居中 + 底部数字（38×32，保留紧凑，字号加大）

保持对外 API 不变（CompactTraitChip / SelectedEmblemTag 构造签名 + clicked 信号）。
"""

from __future__ import annotations

from PyQt6.QtCore import QRect, QRectF, QPoint, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
)
from PyQt6.QtWidgets import QWidget

from ui.image_cache import ImageCache

# ─────────────────────────────────────────────────────────────
# 切换视觉方案：改这一个常量就好
#   "A" → 图标状态芯片（推荐，信息密度高）
#   "B" → 方形增强（更紧凑）
# ─────────────────────────────────────────────────────────────
CHIP_VARIANT = "A"

# ── 色板 ──────────────────────────────────────────────────────
TEXT_PRI    = "#e8eef7"
TEXT_SEC    = "#8b99ad"
TEXT_MUTED  = "#5d6a7e"
TEXT_GOLD   = "#d8b35a"

# 未激活
INACT_BG     = "#151b26"
INACT_BORDER = "#232b3b"
INACT_ICON   = "#2a3344"

# 已激活（按档位）——青铜 / 白银 / 黄金 / 棱彩
TIER_BRONZE = {"bg": "#2a1f18", "edge": "#9e6b3f", "text": "#d89a63"}
TIER_SILVER = {"bg": "#1f2731", "edge": "#b7c4d4", "text": "#dfe8f2"}
TIER_GOLD   = {"bg": "#2a2316", "edge": "#d8b35a", "text": "#f2d37a"}
TIER_PRISM  = {"bg": "#241a2d", "edge": "#c99bff", "text": "#e7c9ff"}  # 也用于双色渐变

# 转职（emblem）
EMBLEM_BG     = "#241a2d"
EMBLEM_EDGE   = "#d8b35a"
EMBLEM_CORNER = "#c89b3c"


def _tier_from_threshold(threshold: int) -> dict:
    """根据激活档位数推断颜色方案；threshold 为 0 代表未激活。"""
    if threshold <= 0:
        return {"bg": INACT_BG, "edge": INACT_BORDER, "text": TEXT_MUTED}
    if threshold <= 2:
        return TIER_BRONZE
    if threshold <= 4:
        return TIER_SILVER
    if threshold <= 6:
        return TIER_GOLD
    return TIER_PRISM


# ─────────────────────────────────────────────────────────────
# 外部尺寸（pick_list 里不直接用，但保留导出防外部脚本 import）
# ─────────────────────────────────────────────────────────────
CHIP_W = 34 if CHIP_VARIANT == "A" else 38
CHIP_H = 32 if CHIP_VARIANT == "A" else 32
EMBLEM_TAG_W = 28
EMBLEM_TAG_H = 28


# ─────────────────────────────────────────────────────────────
# CompactTraitChip
# ─────────────────────────────────────────────────────────────

class CompactTraitChip(QWidget):
    """单个羁绊/转职条目。两种视觉方案由 CHIP_VARIANT 决定。"""

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
        self._hover = False

        self._cache = cache or ImageCache.instance()
        self._px: QPixmap | None = self._cache.get(icon) if icon else None

        self.setFixedSize(CHIP_W, CHIP_H)
        self.setCursor(
            Qt.CursorShape.PointingHandCursor
            if (removable or clickable)
            else Qt.CursorShape.ArrowCursor
        )
        self.setToolTip(tooltip or name)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._cache.image_ready.connect(self._on_ready)

    def _on_ready(self, icon_path: str, px: QPixmap):
        if icon_path == self._icon:
            self._px = px
            self.update()

    def enterEvent(self, _e):
        self._hover = True
        self.update()

    def leaveEvent(self, _e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if (self._removable or self._clickable) and e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._item_key)

    # ── paint dispatch ────────────────────────────────────────
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if CHIP_VARIANT == "A":
            self._paint_variant_a(p)
        else:
            self._paint_variant_b(p)
        p.end()

    # ── 色板解析 ──────────────────────────────────────────────
    def _resolve_palette(self) -> dict:
        if self._is_emblem:
            return {
                "bg": EMBLEM_BG,
                "edge": EMBLEM_EDGE,
                "text": TEXT_GOLD,
                "is_prism": False,
            }
        tier = _tier_from_threshold(self._active_threshold if self._active else 0)
        return {**tier, "is_prism": (self._active_threshold or 0) >= 7}

    # ── Variant A: 图标状态芯片 ──────────────────────────────
    def _paint_variant_a(self, p: QPainter):
        pal = self._resolve_palette()
        w, h = CHIP_W, CHIP_H
        r = 7

        # 背板
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(pal["bg"]))
        p.drawRoundedRect(1, 1, w - 2, h - 2, r, r)

        # 图标
        icon_sz = 22
        icon_x, icon_y = 4, 4
        self._draw_icon(p, icon_x, icon_y, icon_sz, 5, dim=not (self._active or self._is_emblem))

        # 数量角标
        count_text = str(self._current_count)
        count_font = QFont()
        count_font.setPointSize(7)
        count_font.setBold(True)
        p.setFont(count_font)
        pill_w = max(p.fontMetrics().horizontalAdvance(count_text) + 8, 14)
        pill_h = 14
        pill_x = w - pill_w - 1
        pill_y = h - pill_h - 1
        p.setPen(Qt.PenStyle.NoPen)
        pill_bg = QColor(pal["edge"]) if (self._active or self._is_emblem) else QColor("#1f2838")
        p.setBrush(pill_bg)
        p.drawRoundedRect(pill_x, pill_y, pill_w, pill_h, pill_h // 2, pill_h // 2)
        p.setPen(QColor("#0c1018") if (self._active or self._is_emblem) else QColor(TEXT_MUTED))
        p.drawText(QRect(pill_x, pill_y, pill_w, pill_h),
                   Qt.AlignmentFlag.AlignCenter, count_text)

        # 外边框（激活描金/银/铜；未激活浅灰）
        if pal["is_prism"]:
            grad = QLinearGradient(0, 0, w, 0)
            grad.setColorAt(0, QColor("#c99bff"))
            grad.setColorAt(0.5, QColor("#8ad6ff"))
            grad.setColorAt(1, QColor("#ffd17a"))
            p.setPen(QPen(grad, 1.2))
        else:
            edge = QColor(pal["edge"]) if (self._active or self._is_emblem) else QColor(INACT_BORDER)
            p.setPen(QPen(edge, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(1, 1, w - 2, h - 2, r, r)

        # 转职：右上角金色折角
        if self._is_emblem:
            corner = QPainterPath()
            corner.moveTo(w - 10, 1)
            corner.lineTo(w - 1, 1)
            corner.lineTo(w - 1, 10)
            corner.closeSubpath()
            p.fillPath(corner, QColor(EMBLEM_CORNER))

        # hover 高亮
        if self._hover and (self._removable or self._clickable):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 18))
            p.drawRoundedRect(1, 1, w - 2, h - 2, r, r)

    # ── Variant B: 方形增强 ──────────────────────────────────
    def _paint_variant_b(self, p: QPainter):
        pal = self._resolve_palette()
        w, h = CHIP_W, CHIP_H
        r = 7

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(pal["bg"]))
        p.drawRoundedRect(1, 1, w - 2, h - 2, r, r)

        # 图标居中偏上
        icon_sz = 22
        icon_x = (w - icon_sz) // 2
        icon_y = 3
        self._draw_icon(p, icon_x, icon_y, icon_sz, 5, dim=not (self._active or self._is_emblem))

        # 底部数字
        count_font = QFont()
        count_font.setPointSize(7)
        count_font.setBold(True)
        p.setFont(count_font)
        count_color = QColor(pal["text"]) if (self._active or self._is_emblem) else QColor(TEXT_MUTED)
        p.setPen(count_color)
        p.drawText(QRect(0, h - 11, w, 10), Qt.AlignmentFlag.AlignCenter, str(self._current_count))

        # 边框
        if pal["is_prism"]:
            grad = QLinearGradient(0, 0, 0, h)
            grad.setColorAt(0, QColor("#c99bff"))
            grad.setColorAt(1, QColor("#ffd17a"))
            p.setPen(QPen(grad, 1.2))
        else:
            edge = QColor(pal["edge"]) if (self._active or self._is_emblem) else QColor(INACT_BORDER)
            p.setPen(QPen(edge, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(1, 1, w - 2, h - 2, r, r)

        if self._is_emblem:
            corner = QPainterPath()
            corner.moveTo(w - 9, 1)
            corner.lineTo(w - 1, 1)
            corner.lineTo(w - 1, 9)
            corner.closeSubpath()
            p.fillPath(corner, QColor(EMBLEM_CORNER))

        if self._hover and (self._removable or self._clickable):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 18))
            p.drawRoundedRect(1, 1, w - 2, h - 2, r, r)

    # ── helper: 圆角图标 ─────────────────────────────────────
    def _draw_icon(self, p: QPainter, x: int, y: int, sz: int, r: int, dim: bool):
        clip = QPainterPath()
        clip.addRoundedRect(x, y, sz, sz, r, r)
        p.save()
        p.setClipPath(clip)
        if self._px:
            src = self._px
            side = min(src.width(), src.height())
            sx = (src.width() - side) // 2
            sy = (src.height() - side) // 2
            p.drawPixmap(QRect(x, y, sz, sz), src, QRect(sx, sy, side, side))
            if dim:
                p.fillRect(x, y, sz, sz, QColor(0, 0, 0, 130))
        else:
            p.fillRect(x, y, sz, sz, QColor(INACT_ICON))
        p.restore()


# ─────────────────────────────────────────────────────────────
# SelectedEmblemTag — 顶部已选转职图标
# 放大到 28×28，去掉红点改为 hover 遮罩 ×
# ─────────────────────────────────────────────────────────────

class SelectedEmblemTag(QWidget):
    """标题行里的已选转职图标。hover 时显示移除遮罩。"""

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
        self._hover = False

        self._cache = cache or ImageCache.instance()
        self._px: QPixmap | None = self._cache.get(icon) if icon else None

        self.setFixedSize(EMBLEM_TAG_W, EMBLEM_TAG_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tooltip or name)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._cache.image_ready.connect(self._on_ready)

    def _on_ready(self, icon_path: str, px: QPixmap):
        if icon_path == self._icon:
            self._px = px
            self.update()

    def enterEvent(self, _e):
        self._hover = True
        self.update()

    def leaveEvent(self, _e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._item_key)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        w, h = EMBLEM_TAG_W, EMBLEM_TAG_H

        # 背板 + 金边
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(EMBLEM_BG))
        p.drawRoundedRect(1, 1, w - 2, h - 2, 7, 7)

        # 图标
        icon_sz = 20
        ix = (w - icon_sz) // 2
        iy = (h - icon_sz) // 2
        clip = QPainterPath()
        clip.addRoundedRect(ix, iy, icon_sz, icon_sz, 5, 5)
        p.save()
        p.setClipPath(clip)
        if self._px:
            src = self._px
            side = min(src.width(), src.height())
            sx = (src.width() - side) // 2
            sy = (src.height() - side) // 2
            p.drawPixmap(QRect(ix, iy, icon_sz, icon_sz), src, QRect(sx, sy, side, side))
        else:
            p.fillRect(ix, iy, icon_sz, icon_sz, QColor(INACT_ICON))
        p.restore()

        # 金边
        p.setPen(QPen(QColor(EMBLEM_EDGE), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(1, 1, w - 2, h - 2, 7, 7)

        # 右上角折角
        corner = QPainterPath()
        corner.moveTo(w - 9, 1)
        corner.lineTo(w - 1, 1)
        corner.lineTo(w - 1, 9)
        corner.closeSubpath()
        p.fillPath(corner, QColor(EMBLEM_CORNER))

        # hover 移除遮罩
        if self._hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 165))
            p.drawRoundedRect(1, 1, w - 2, h - 2, 7, 7)
            p.setPen(QColor("#ff8a8a"))
            f = QFont()
            f.setPointSize(10)
            f.setBold(True)
            p.setFont(f)
            p.drawText(QRect(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, "×")

        p.end()
