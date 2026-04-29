"""
TFT Assistant — 英雄卡片 Widget
================================
显示单个英雄的头像 + 费用徽章 + 出装图标（部分重叠在头像下方）。

视觉布局（每张卡片 60×72px）：
  ┌──────────────────────┐
  │  ┌──────────────┐  ● │  ← 56×56 头像 + 费用徽章右上角
  │  │ [名字覆盖层] │    │  ← 英雄名半透明黑条覆盖在头像上半部分
  │  │  avatar      │    │
  │  └──┬───┬───┬───┘    │
  │  [i][i][i]           │  ← 3个装备图标 18×18，总宽=56=AVATAR_SZ
  └──────────────────────┘
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QRect, QPoint
from PyQt6.QtGui import (
    QColor, QFont, QPainter, QPainterPath, QPixmap, QPen, QBrush,
)
from PyQt6.QtWidgets import QWidget, QFrame, QHBoxLayout, QVBoxLayout, QLabel

from data.models import Unit
from ui.image_cache import ImageCache

# ── 尺寸常量 ─────────────────────────────────────────────────
CARD_W    = 60
CARD_H    = 72
AVATAR_SZ = 56
ITEM_SZ   = 18     # 3×18 + 2×1 = 56 = AVATAR_SZ
ITEM_GAP  = 1
BADGE_SZ  = 16
OVERLAP   = 8    # 装备图标与头像的重叠像素

# ── 费用颜色 ──────────────────────────────────────────────────
COST_COLORS = {
    1: "#5d6168",
    2: "#2a7a36",
    3: "#1a5fa8",
    4: "#8b3fa8",
    5: "#c89b3c",
}

# ── 调色板 ────────────────────────────────────────────────────
AVATAR_BG   = QColor("#1e2433")
ITEM_BG     = QColor("#252d3d")
NAME_COLOR  = QColor("#e2e8f0")
BORDER_DARK = QColor("#0a0c10")
NAME_OVERLAY_BG = QColor(0, 0, 0, 140)   # 半透明黑色遮罩
TEXT_SEC = "#8b99ad"
TEXT_PRI = "#e2e8f0"
TEXT_GOLD = "#c89b3c"
POPUP_BG = "#111823"
POPUP_PANEL = "#1b2635"
POPUP_BORDER = "#c89b3c"


def _txt(text: str, color: str = TEXT_PRI, size: int = 10, bold: bool = False) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(
        f"color:{color}; font-size:{size}px; font-weight:{'700' if bold else '500'};"
        " background:transparent;"
    )
    return label


class _InfoIcon(QWidget):
    """浮层里的头像/装备图标。"""

    def __init__(
        self,
        icon: str,
        cache: ImageCache,
        *,
        name: str = "",
        cost: int | None = None,
        category: str = "",
        size: int = 28,
        parent=None,
    ):
        super().__init__(parent)
        self._icon = icon
        self._name = name
        self._cost = cost
        self._category = category
        self._size = size
        self._cache = cache
        self._px: QPixmap | None = cache.get(icon) if icon else None

        self.setFixedSize(size, size)
        self.setToolTip(name)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        cache.image_ready.connect(self._on_ready)

    def _on_ready(self, icon_path: str, px: QPixmap):
        if icon_path == self._icon:
            self._px = px
            self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        sz = self._size
        path = QPainterPath()
        path.addRoundedRect(0, 0, sz, sz, 5, 5)
        p.fillPath(path, QColor("#1e2433"))
        p.setClipPath(path)

        if self._px:
            src = self._px
            side = min(src.width(), src.height())
            sx = (src.width() - side) // 2
            sy = (src.height() - side) // 2
            p.drawPixmap(QRect(0, 0, sz, sz), src, QRect(sx, sy, side, side))

        p.setClipping(False)
        p.setPen(QPen(self._border_color(), 1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(1, 1, sz - 2, sz - 2, 5, 5)
        p.end()

    def _border_color(self) -> QColor:
        if self._cost:
            return QColor(COST_COLORS.get(self._cost, "#5d6168"))
        if self._category == "emblem":
            return QColor("#d8b35a")
        if self._category == "artifact":
            return QColor("#a68cff")
        if self._category == "radiant":
            return QColor("#e8d17a")
        return QColor("#2e3d52")


class UnitInfoPopup(QFrame):
    """英雄 hover 浮层：用图标承载出装和装备优先级。"""

    def __init__(self, unit: Unit, cache: ImageCache, parent=None):
        super().__init__(parent, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.unit = unit
        self.cache = cache
        self.setObjectName("unit-info-popup")
        self.setStyleSheet(f"""
            QFrame#unit-info-popup {{
                background:{POPUP_BG};
                border:1px solid {POPUP_BORDER};
                border-radius:6px;
            }}
        """)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        header.addWidget(_InfoIcon(
            self.unit.icon, self.cache,
            name=self.unit.name, cost=self.unit.cost, size=34,
        ))
        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(1)
        title_col.addWidget(_txt(self.unit.name, TEXT_PRI, 12, True))
        cost = f"{self.unit.cost}费" if self.unit.cost is not None else "费用未知"
        title_col.addWidget(_txt(cost, TEXT_SEC, 9))
        header.addLayout(title_col)
        header.addStretch()
        root.addLayout(header)

        for build in self.unit.builds[:2]:
            if build.items:
                root.addWidget(self._icon_row(f"出装{build.index}", build.items[:3]))

        if self.unit.item_priority:
            priority_items = sorted(
                self.unit.item_priority,
                key=lambda item: item.necessity,
                reverse=True,
            )[:5]
            root.addWidget(self._priority_row(priority_items))

        stats_text = self._stats_text()
        if stats_text:
            stat = _txt(stats_text, TEXT_SEC, 9)
            stat.setStyleSheet(
                f"color:{TEXT_SEC}; font-size:9px; font-weight:500;"
                f" background:{POPUP_PANEL}; border-radius:4px; padding:4px 6px;"
            )
            root.addWidget(stat)

    def _icon_row(self, label: str, items):
        row = QFrame()
        row.setStyleSheet(f"background:{POPUP_PANEL}; border:none; border-radius:4px;")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(7, 5, 7, 5)
        lay.setSpacing(5)
        kind = _txt(label, TEXT_GOLD, 9, True)
        kind.setFixedWidth(42)
        lay.addWidget(kind)
        for item in items:
            lay.addWidget(_InfoIcon(
                item.icon, self.cache,
                name=item.name, category=item.category, size=26,
            ))
        lay.addStretch()
        return row

    def _priority_row(self, priority_items):
        row = QFrame()
        row.setStyleSheet(f"background:{POPUP_PANEL}; border:none; border-radius:4px;")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(7, 5, 7, 5)
        lay.setSpacing(5)
        kind = _txt("优先", TEXT_GOLD, 9, True)
        kind.setFixedWidth(42)
        lay.addWidget(kind)
        for item in priority_items:
            if not item.icon:
                continue
            freq = f"{item.appearance_rate * 100:.1f}%" if item.appearance_rate else ""
            tooltip = item.name
            if item.rating or freq:
                tooltip += f"\n{item.rating} {freq}".strip()
            lay.addWidget(_InfoIcon(
                item.icon,
                self.cache,
                name=tooltip, category=item.category, size=26,
            ))
        lay.addStretch()
        return row

    def _stats_text(self) -> str:
        metrics = self.unit.stats.get("metrics") if self.unit.stats else None
        if not metrics:
            return ""
        sample = metrics[0] if len(metrics) > 0 else "—"
        avg = metrics[4] if len(metrics) > 4 else (metrics[2] if len(metrics) > 2 else "—")
        rate = metrics[1] if len(metrics) > 1 else ""
        return f"样本 {sample}   均名 {avg}" + (f"   出场 {rate}" if rate else "")


class UnitCard(QWidget):
    """
    单英雄卡片。接受 Unit dataclass 和 ImageCache。
    图片异步加载：ImageCache 发射 image_ready 时自动刷新。
    """

    def __init__(self, unit: Unit, cache: ImageCache, parent=None):
        super().__init__(parent)
        self.unit   = unit
        self.cache  = cache
        self.setFixedSize(CARD_W, CARD_H)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)

        self._avatar_px: QPixmap | None = None
        self._item_px:   list[QPixmap | None] = [None, None, None]
        self._popup: UnitInfoPopup | None = None

        self._load_images()
        cache.image_ready.connect(self._on_image_ready)

    # ──────────────────────────────────────────────────────────
    # 图片加载
    # ──────────────────────────────────────────────────────────

    def _load_images(self):
        if self.unit.icon:
            self._avatar_px = self.cache.get(self.unit.icon)

        items = self._items()
        for idx, item in enumerate(items):
            if item.icon:
                self._item_px[idx] = self.cache.get(item.icon)
        for build in self.unit.builds[1:3]:
            for item in build.items[:3]:
                if item.icon:
                    self.cache.get(item.icon)
        for item in self.unit.item_priority[:5]:
            if item.icon:
                self.cache.get(item.icon)

    def _items(self):
        """取第一套出装的前3件。"""
        if self.unit.builds:
            return self.unit.builds[0].items[:3]
        return []

    def _on_image_ready(self, icon_path: str, px: QPixmap):
        changed = False
        if icon_path == self.unit.icon:
            self._avatar_px = px
            changed = True
        for idx, item in enumerate(self._items()):
            if item.icon == icon_path:
                self._item_px[idx] = px
                changed = True
        if changed:
            self.update()

    # ──────────────────────────────────────────────────────────
    # Hover 浮层
    # ──────────────────────────────────────────────────────────

    def enterEvent(self, _event):
        self._show_info_popup()

    def leaveEvent(self, _event):
        self._hide_info_popup()

    def _show_info_popup(self):
        if self._popup is not None:
            self._popup.close()
            self._popup.deleteLater()

        self._popup = UnitInfoPopup(self.unit, self.cache, self)
        self._popup.adjustSize()

        pos = self.mapToGlobal(QPoint(CARD_W + 8, -8))
        screen = self.screen()
        if screen:
            bounds = screen.availableGeometry()
            if pos.x() + self._popup.width() > bounds.right():
                pos.setX(self.mapToGlobal(QPoint(-self._popup.width() - 8, -8)).x())
            if pos.y() + self._popup.height() > bounds.bottom():
                pos.setY(bounds.bottom() - self._popup.height() - 8)
            if pos.y() < bounds.top():
                pos.setY(bounds.top() + 8)

        self._popup.move(pos)
        self._popup.show()

    def _hide_info_popup(self):
        if self._popup is not None:
            self._popup.close()
            self._popup.deleteLater()
            self._popup = None

    # ──────────────────────────────────────────────────────────
    # 绘制
    # ──────────────────────────────────────────────────────────

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        avatar_x = (CARD_W - AVATAR_SZ) // 2   # 水平居中
        avatar_y = 0

        self._draw_avatar(p, avatar_x, avatar_y)
        self._draw_name_overlay(p, avatar_x, avatar_y)
        self._draw_cost_badge(p, avatar_x, avatar_y)
        self._draw_items(p, avatar_x, avatar_y)
        p.end()

    def _draw_avatar(self, p: QPainter, x: int, y: int):
        radius = 5
        cost   = self.unit.cost or 1
        border_color = QColor(COST_COLORS.get(cost, "#5d6168"))

        clip = QPainterPath()
        clip.addRoundedRect(x, y, AVATAR_SZ, AVATAR_SZ, radius, radius)
        p.setClipPath(clip)

        if self._avatar_px:
            src  = self._avatar_px
            side = min(src.width(), src.height())
            sx   = (src.width()  - side) // 2
            sy   = (src.height() - side) // 2
            p.drawPixmap(
                QRect(x, y, AVATAR_SZ, AVATAR_SZ),
                src, QRect(sx, sy, side, side),
            )
        else:
            p.fillRect(x, y, AVATAR_SZ, AVATAR_SZ, AVATAR_BG)

        p.setClipping(False)

        # 费用色边框
        pen = QPen(border_color, 2)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(x + 1, y + 1, AVATAR_SZ - 2, AVATAR_SZ - 2, radius, radius)

    def _draw_name_overlay(self, p: QPainter, avatar_x: int, avatar_y: int):
        """在头像上半部分绘制半透明黑条 + 英雄名。"""
        overlay_h = 18
        radius    = 5

        # 剪裁路径：只在头像区域内绘制（上部圆角）
        clip = QPainterPath()
        clip.addRoundedRect(avatar_x, avatar_y, AVATAR_SZ, AVATAR_SZ, radius, radius)
        p.setClipPath(clip)

        # 半透明遮罩
        p.fillRect(
            avatar_x, avatar_y,
            AVATAR_SZ, overlay_h,
            NAME_OVERLAY_BG,
        )
        p.setClipping(False)

        # 英雄名文字
        f = QFont()
        f.setPointSize(7)
        f.setBold(True)
        p.setFont(f)
        p.setPen(NAME_COLOR)

        metrics = p.fontMetrics()
        name    = metrics.elidedText(
            self.unit.name, Qt.TextElideMode.ElideRight, AVATAR_SZ - 4
        )
        p.drawText(
            QRect(avatar_x, avatar_y, AVATAR_SZ, overlay_h),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            name,
        )

    def _draw_cost_badge(self, p: QPainter, avatar_x: int, avatar_y: int):
        cost = self.unit.cost
        if cost is None:
            return
        # 右上角，稍微嵌入
        bx = avatar_x + AVATAR_SZ - BADGE_SZ + 2
        by = avatar_y - 2

        color = QColor(COST_COLORS.get(cost, "#5d6168"))
        p.setBrush(QBrush(color))
        p.setPen(QPen(BORDER_DARK, 1))
        p.drawRoundedRect(bx, by, BADGE_SZ, BADGE_SZ, BADGE_SZ // 2, BADGE_SZ // 2)

        p.setPen(QColor("white"))
        f = QFont()
        f.setPointSize(7)
        f.setBold(True)
        p.setFont(f)
        p.drawText(
            QRect(bx, by, BADGE_SZ, BADGE_SZ),
            Qt.AlignmentFlag.AlignCenter,
            str(cost),
        )

    def _draw_items(self, p: QPainter, avatar_x: int, avatar_y: int):
        items = self._items()
        n     = len(items)
        if n == 0:
            return

        # 3×18 + 2×1 = 56 = AVATAR_SZ，完全对齐头像宽度
        total_w = n * ITEM_SZ + (n - 1) * ITEM_GAP
        start_x = avatar_x + (AVATAR_SZ - total_w) // 2
        item_y  = avatar_y + AVATAR_SZ - OVERLAP

        for idx in range(n):
            ix = start_x + idx * (ITEM_SZ + ITEM_GAP)
            iy = item_y

            path = QPainterPath()
            path.addRoundedRect(ix, iy, ITEM_SZ, ITEM_SZ, 3, 3)
            p.fillPath(path, QBrush(ITEM_BG))

            px = self._item_px[idx] if idx < len(self._item_px) else None
            if px:
                p.setClipPath(path)
                p.drawPixmap(QRect(ix, iy, ITEM_SZ, ITEM_SZ), px)
                p.setClipping(False)

            p.setPen(QPen(BORDER_DARK, 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(ix, iy, ITEM_SZ, ITEM_SZ, 3, 3)
