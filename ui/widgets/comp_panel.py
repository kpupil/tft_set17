"""
TFT Assistant — 阵容详情面板
==============================
整个助手的核心面板，布局（宽 340px）：

  ┌─────────────────────────────────────┐
  │  [▾ 阵容下拉]         ★3.64  17.7% │  ← 顶栏
  ├─────────────────────────────────────┤
  │  [英雄1]  [英雄2]  ...  [英雄5]   │  ← 英雄卡片行（5列换行）
  │  [英雄6]  [英雄7]  ...             │
  ├─────────────────────────────────────┤
  │  ▶ 变体阵容 (3)                    │  ← 可折叠，展开向下延伸
  │    [头像][头像]...                  │
  └─────────────────────────────────────┘
"""

from __future__ import annotations

from collections import Counter

from PyQt6.QtCore import Qt, QRect, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap, QPen, QBrush, QCursor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QFrame, QGridLayout,
    QSizePolicy, QPushButton, QScrollArea,
)

from data.manager import DataManager
from data.models import Composition
from ui.image_cache import ImageCache

# ── 调色板 ─────────────────────────────────────────────────────
BG_SECTION  = "#141922"
BG_HOVER    = "#1e2736"
BORDER      = "#252d3d"
TEXT_PRI    = "#e2e8f0"
TEXT_SEC    = "#7a8a9e"
TEXT_GOLD   = "#c89b3c"
CHIP_BG     = "#1e2736"
CHIP_BORDER = "#2e3d52"

COST_COLORS = {1: "#5d6168", 2: "#2a7a36", 3: "#1a5fa8", 4: "#8b3fa8", 5: "#c89b3c"}

# ── MiniUnitCard 尺寸 ──────────────────────────────────────────
MINI_SZ    = 28   # 小头像边长
MINI_BADGE = 10   # 小费用徽章


def _label(text: str, color: str = TEXT_PRI, size: int = 10,
           bold: bool = False) -> QLabel:
    lbl = QLabel(text)
    w = "600" if bold else "400"
    lbl.setStyleSheet(f"color:{color}; font-size:{size}px; font-weight:{w};"
                      f" background:transparent;")
    return lbl


def _hline() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet(f"color:{BORDER}; background:{BORDER};")
    f.setFixedHeight(1)
    return f


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.1f}%"


def _fmt_place(value: float | int | str | None) -> str:
    if value in (None, "", 0):
        return "—"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _sort_float(value, default: float = 9.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ─────────────────────────────────────────────────────────────
# 小头像 Widget（变体阵容用）
# ─────────────────────────────────────────────────────────────

class MiniUnitCard(QWidget):
    """28×28 小头像，带费用色边框，无装备/名称。"""

    def __init__(self, unit_data: dict, cache: ImageCache, parent=None):
        super().__init__(parent)
        self._id   = unit_data.get("id", "")
        self._cost = unit_data.get("cost") or 1
        self._icon = unit_data.get("icon", "")
        self._name = unit_data.get("name", "")
        self.cache = cache

        self.setFixedSize(MINI_SZ, MINI_SZ)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setToolTip(self._name)

        self._px: QPixmap | None = None
        if self._icon:
            self._px = cache.get(self._icon)
        cache.image_ready.connect(self._on_ready)

    def _on_ready(self, icon_path: str, px: QPixmap):
        if icon_path == self._icon:
            self._px = px
            self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        border_color = QColor(COST_COLORS.get(self._cost, "#5d6168"))
        radius = 4

        # 圆角裁剪
        clip = QPainterPath()
        clip.addRoundedRect(0, 0, MINI_SZ, MINI_SZ, radius, radius)
        p.setClipPath(clip)

        if self._px:
            src  = self._px
            side = min(src.width(), src.height())
            sx   = (src.width()  - side) // 2
            sy   = (src.height() - side) // 2
            p.drawPixmap(
                QRect(0, 0, MINI_SZ, MINI_SZ),
                src, QRect(sx, sy, side, side),
            )
        else:
            p.fillRect(0, 0, MINI_SZ, MINI_SZ, QColor("#1e2433"))

        p.setClipping(False)

        # 费用色边框
        p.setPen(QPen(border_color, 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(1, 1, MINI_SZ - 2, MINI_SZ - 2, radius, radius)

        # 费用徽章（右下角）
        bsz = MINI_BADGE
        bx  = MINI_SZ - bsz
        by  = MINI_SZ - bsz
        p.setBrush(QBrush(border_color))
        p.setPen(QPen(QColor("#0a0c10"), 1))
        p.drawRoundedRect(bx, by, bsz, bsz, bsz // 2, bsz // 2)

        p.setPen(QColor("white"))
        f = QFont()
        f.setPointSize(6)
        f.setBold(True)
        p.setFont(f)
        p.drawText(
            QRect(bx, by, bsz, bsz),
            Qt.AlignmentFlag.AlignCenter,
            str(self._cost),
        )

        p.end()


# ─────────────────────────────────────────────────────────────
# 变体阵容行
# ─────────────────────────────────────────────────────────────

class VariantRow(QFrame):
    """单条变体阵容行：小头像横排 + 导入按钮。"""

    import_requested = pyqtSignal(list)   # 携带 unit dict 列表

    def __init__(self, idx: int, variant, cache: ImageCache):
        super().__init__()
        self._variant = variant
        self.setStyleSheet(f"background:{CHIP_BG}; border-radius:4px;")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 5, 8, 5)
        lay.setSpacing(3)

        lay.addWidget(_label(f"变体{idx}", TEXT_GOLD, 9, bold=True))
        lay.addSpacing(4)

        for unit_data in variant.units[:10]:
            mini = MiniUnitCard(
                {"id": unit_data.id, "cost": unit_data.cost,
                 "icon": unit_data.icon, "name": unit_data.name},
                cache,
            )
            lay.addWidget(mini)

        lay.addStretch()


class VariantsSection(QWidget):
    """可折叠的变体阵容区块。展开后内容向下延伸，不挤占上方空间。"""

    import_requested = pyqtSignal(list)   # 透传 VariantRow 的信号

    def __init__(self, variants: list, cache: ImageCache):
        super().__init__()
        self._variants = variants
        self._cache    = cache
        self._expanded = False
        self._setup_ui()

    def _setup_ui(self):
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(0)

        # 折叠头部
        self._header = QPushButton()
        self._header.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._header.setStyleSheet(f"""
            QPushButton {{
                background: {BG_SECTION};
                border: none;
                border-top: 1px solid {BORDER};
                color: {TEXT_SEC};
                font-size: 10px;
                text-align: left;
                padding: 7px 12px;
            }}
            QPushButton:hover {{
                background: {BG_HOVER};
                color: {TEXT_PRI};
            }}
        """)
        self._update_header_text()
        self._header.clicked.connect(self._toggle)
        self._outer.addWidget(self._header)

        # 内容容器（懒加载：首次展开时才构建）
        self._body: QWidget | None = None

    def _build_body(self):
        self._body = QWidget()
        body_lay = QVBoxLayout(self._body)
        body_lay.setContentsMargins(8, 4, 8, 8)
        body_lay.setSpacing(4)
        for i, v in enumerate(self._variants[:5], 1):
            units = [
                {"id": u.id, "name": u.name, "cost": u.cost or 1, "icon": u.icon}
                for u in v.units
            ]

            # 卡片：左侧「变体N / 导入」列 + 右侧头像行
            card = QWidget()
            card.setStyleSheet(f"background:{CHIP_BG}; border-radius:4px;")
            card_lay = QHBoxLayout(card)
            card_lay.setContentsMargins(8, 5, 8, 5)
            card_lay.setSpacing(8)

            # 左列：变体编号 + 导入按钮，垂直居中
            left = QWidget()
            left.setStyleSheet("background:transparent;")
            left_lay = QVBoxLayout(left)
            left_lay.setContentsMargins(0, 0, 0, 0)
            left_lay.setSpacing(2)
            left_lay.setAlignment(Qt.AlignmentFlag.AlignVCenter)

            lbl = _label(f"变体{i}", TEXT_GOLD, 9, bold=True)
            left_lay.addWidget(lbl)

            stats = v.stats or {}
            meta_bits = []
            if stats.get("avg_placement") is not None:
                meta_bits.append(f"{_fmt_place(stats.get('avg_placement'))}名")
            if stats.get("share") is not None:
                meta_bits.append(_fmt_pct(stats.get("share")))
            if meta_bits:
                meta = _label(meta_bits[0], TEXT_SEC, 8)
                left_lay.addWidget(meta)

            import_btn = QPushButton("导入")
            import_btn.setFixedSize(34, 16)
            import_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            import_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; border: none;
                    color: {TEXT_SEC}; font-size: 9px;
                    text-align: left; padding: 0;
                }}
                QPushButton:hover {{ color: {TEXT_PRI}; }}
            """)
            import_btn.clicked.connect(
                lambda _, us=units: self.import_requested.emit(us)
            )
            left_lay.addWidget(import_btn)
            left.setFixedWidth(48)
            card_lay.addWidget(left)

            # 右侧：头像横排
            avatars = QWidget()
            avatars.setStyleSheet("background:transparent;")
            av_lay = QHBoxLayout(avatars)
            av_lay.setContentsMargins(0, 0, 0, 0)
            av_lay.setSpacing(3)
            for unit_data in v.units[:10]:
                mini = MiniUnitCard(
                    {"id": unit_data.id, "cost": unit_data.cost,
                     "icon": unit_data.icon, "name": unit_data.name},
                    self._cache,
                )
                av_lay.addWidget(mini)
            av_lay.addStretch()
            card_lay.addWidget(avatars, stretch=1)
            if meta_bits:
                card.setToolTip("变体统计：" + " / ".join(meta_bits))

            body_lay.addWidget(card)
        self._outer.addWidget(self._body)

    def _update_header_text(self):
        arrow = "▼" if self._expanded else "▶"
        n     = len(self._variants)
        self._header.setText(f"  {arrow}  变体阵容  ({n})")

    def _toggle(self):
        self._expanded = not self._expanded
        if self._expanded:
            if self._body is None:
                self._build_body()
            self._body.setVisible(True)
        else:
            if self._body:
                self._body.setVisible(False)
        self._update_header_text()
        # 无需手动 resize — overlay 的 SetFixedSize layout 约束
        # 会在 show/hide 触发 layout 变化时自动调整窗口高度


class AdvancedIcon(QWidget):
    """进阶信息里的装备/英雄小图标。"""

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

        r = 5
        sz = self._size
        border = self._border_color()

        path = QPainterPath()
        path.addRoundedRect(0, 0, sz, sz, r, r)
        p.fillPath(path, QColor("#111722"))
        p.setClipPath(path)

        if self._px:
            src = self._px
            side = min(src.width(), src.height())
            sx = (src.width() - side) // 2
            sy = (src.height() - side) // 2
            p.drawPixmap(QRect(0, 0, sz, sz), src, QRect(sx, sy, side, side))
        else:
            p.fillRect(0, 0, sz, sz, QColor("#1e2433"))

        p.setClipping(False)
        p.setPen(QPen(border, 1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(1, 1, sz - 2, sz - 2, r, r)
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
        return QColor(CHIP_BORDER)


class AdvancedVisualRow(QFrame):
    """一行图像化进阶信息：装备图标 → 携带者头像 + 少量统计。"""

    def __init__(
        self,
        kind: str,
        source: dict,
        cache: ImageCache,
        *,
        target: dict | None = None,
        build_items: list[dict] | None = None,
        stat: str = "",
        tooltip: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.setStyleSheet(f"background:{CHIP_BG}; border-radius:5px;")
        self.setToolTip(tooltip)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 5, 8, 5)
        lay.setSpacing(6)

        kind_lbl = _label(kind, TEXT_GOLD, 9, bold=True)
        kind_lbl.setFixedWidth(34)
        lay.addWidget(kind_lbl)

        lay.addWidget(AdvancedIcon(
            source.get("icon", ""),
            cache,
            name=source.get("name", ""),
            category=source.get("category", ""),
            size=28,
        ))

        if target:
            arrow = _label("→", TEXT_SEC, 10, bold=True)
            arrow.setFixedWidth(12)
            lay.addWidget(arrow)
            lay.addWidget(AdvancedIcon(
                target.get("icon", ""),
                cache,
                name=target.get("name", ""),
                cost=target.get("cost"),
                size=28,
            ))

        for item in (build_items or [])[:3]:
            lay.addWidget(AdvancedIcon(
                item.get("icon", ""),
                cache,
                name=item.get("name", ""),
                category=item.get("category", ""),
                size=20,
            ))

        lay.addStretch()

        if stat:
            stat_lbl = _label(stat, TEXT_SEC, 9)
            stat_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            stat_lbl.setMinimumWidth(58)
            lay.addWidget(stat_lbl)


class UnitStatsStrip(QFrame):
    """单位统计摘要：用头像扫读核心单位，详细数字放 tooltip。"""

    def __init__(self, units: list[dict], cache: ImageCache, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{CHIP_BG}; border-radius:5px;")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 5, 8, 5)
        lay.setSpacing(6)

        kind_lbl = _label("单位", TEXT_GOLD, 9, bold=True)
        kind_lbl.setFixedWidth(34)
        lay.addWidget(kind_lbl)

        for unit in units[:6]:
            metrics = unit.get("metrics") or []
            tooltip = unit.get("name", "")
            if metrics:
                tooltip += "\n" + " | ".join(str(m) for m in metrics[:6])
            icon = AdvancedIcon(
                unit.get("icon", ""),
                cache,
                name=tooltip,
                cost=unit.get("cost"),
                size=28,
            )
            lay.addWidget(icon)

        lay.addStretch()


# ─────────────────────────────────────────────────────────────
# 进阶信息区
# ─────────────────────────────────────────────────────────────

class AdvancedInfoSection(QWidget):
    """默认折叠的图像化进阶信息：转职、特殊装备、单位统计。"""

    def __init__(self, comp: Composition, cache: ImageCache):
        super().__init__()
        self._comp = comp
        self._cache = cache
        self._expanded = False
        self._setup_ui()

    def _setup_ui(self):
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(0)

        self._header = QPushButton()
        self._header.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._header.setStyleSheet(f"""
            QPushButton {{
                background: {BG_SECTION};
                border: none;
                border-top: 1px solid {BORDER};
                color: {TEXT_SEC};
                font-size: 10px;
                text-align: left;
                padding: 7px 12px;
            }}
            QPushButton:hover {{
                background: {BG_HOVER};
                color: {TEXT_PRI};
            }}
        """)
        self._header.clicked.connect(self._toggle)
        self._outer.addWidget(self._header)

        self._body = QWidget()
        body_lay = QVBoxLayout(self._body)
        body_lay.setContentsMargins(8, 4, 8, 8)
        body_lay.setSpacing(5)

        self._fill_body(body_lay)
        self._body.hide()
        self._outer.addWidget(self._body)
        self._update_header_text()

    def _fill_body(self, body_lay: QVBoxLayout):
        for emblem in self._best_emblems()[:4]:
            carrier = self._best_carrier(emblem.get("carriers", []))
            meta = f"{_fmt_place(emblem.get('avg_placement'))}名  {_fmt_pct(emblem.get('appearance_rate'))}"
            carrier_name = carrier.get("name", "—") if carrier else "—"
            tooltip = f"{emblem.get('name', '—')} → {carrier_name}\n{meta}"
            body_lay.addWidget(AdvancedVisualRow(
                "转职",
                emblem,
                self._cache,
                target=carrier,
                stat=meta,
                tooltip=tooltip,
            ))

        special_items = self._best_special_items()
        if special_items:
            special_host = QWidget()
            special_host.setStyleSheet("background:transparent;")
            special_lay = QVBoxLayout(special_host)
            special_lay.setContentsMargins(0, 0, 0, 0)
            special_lay.setSpacing(5)

            for item in special_items:
                special_lay.addWidget(self._special_item_row(item))
            special_lay.addStretch()

            if len(special_items) > 6:
                scroll = QScrollArea()
                scroll.setWidgetResizable(True)
                scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
                scroll.setFrameShape(QFrame.Shape.NoFrame)
                scroll.setFixedHeight(260)
                scroll.setStyleSheet("""
                    QScrollArea { background: transparent; border:none; }
                    QScrollBar:vertical {
                        background: transparent;
                        width: 5px;
                        margin: 2px 0 2px 0;
                    }
                    QScrollBar::handle:vertical {
                        background: #3c5070;
                        border-radius: 2px;
                        min-height: 24px;
                    }
                    QScrollBar::handle:vertical:hover {
                        background: #c89b3c;
                    }
                    QScrollBar::add-line:vertical,
                    QScrollBar::sub-line:vertical {
                        height: 0;
                        background: transparent;
                    }
                    QScrollBar::add-page:vertical,
                    QScrollBar::sub-page:vertical {
                        background: transparent;
                    }
                """)
                scroll.setWidget(special_host)
                body_lay.addWidget(scroll)
            else:
                body_lay.addWidget(special_host)

        core_units = self._core_unit_stats()
        if core_units:
            body_lay.addWidget(UnitStatsStrip(core_units, self._cache))

    def _special_item_row(self, item: dict) -> AdvancedVisualRow:
        carrier = item.get("carrier") or {}
        avg = self._special_item_avg(item)
        metrics = item.get("metrics") or []
        stat = _fmt_place(avg)
        if stat != "—":
            stat += "名"
        if len(metrics) > 1 and metrics[1]:
            stat = f"{stat}  {metrics[1]}" if stat != "—" else str(metrics[1])
        best_build = item.get("best_build") or {}
        build_items = best_build.get("items", []) or []
        tooltip = f"{item.get('name', '—')} → {carrier.get('name', '—')}"
        if stat:
            tooltip += f"\n{stat}"
        if build_items:
            tooltip += "\n最佳出装：" + " / ".join(i.get("name", "") for i in build_items)
        return AdvancedVisualRow(
            self._category_label(item.get("category", "")),
            item,
            self._cache,
            target=carrier,
            build_items=build_items,
            stat=stat,
            tooltip=tooltip,
        )

    def _best_emblems(self) -> list[dict]:
        return sorted(
            self._comp.emblems,
            key=lambda e: e.get("avg_placement") or 9.0,
        )

    def _best_carrier(self, carriers: list[dict]) -> dict | None:
        for carrier in carriers:
            if carrier.get("best"):
                return carrier
        return carriers[0] if carriers else None

    def _special_item_avg(self, item: dict):
        best_build = item.get("best_build") or {}
        if best_build.get("avg_placement"):
            return best_build.get("avg_placement")
        metrics = item.get("metrics") or []
        return metrics[3] if len(metrics) > 3 else None

    def _best_special_items(self) -> list[dict]:
        return sorted(
            self._comp.special_items,
            key=lambda item: _sort_float(self._special_item_avg(item)),
        )

    def _core_unit_stats(self) -> list[dict]:
        return sorted(
            [u for u in self._comp.unit_stats if u.get("metrics")],
            key=lambda u: (-(u.get("cost") or 0), u.get("name", "")),
        )

    def _category_label(self, category: str) -> str:
        if category == "artifact":
            return "神器"
        if category == "radiant":
            return "光明"
        if category == "emblem":
            return "转职"
        return "特装"

    def _update_header_text(self):
        arrow = "▼" if self._expanded else "▶"
        parts = []
        if self._comp.emblems:
            parts.append(f"转职{len(self._comp.emblems)}")
        if self._comp.special_items:
            parts.append(f"特装{len(self._comp.special_items)}")
        if self._comp.unit_stats:
            parts.append(f"单位{len(self._comp.unit_stats)}")
        suffix = " / ".join(parts) if parts else "无"
        self._header.setText(f"  {arrow}  进阶信息  ({suffix})")

    def _toggle(self):
        self._expanded = not self._expanded
        self._body.setVisible(self._expanded)
        self._update_header_text()


# ─────────────────────────────────────────────────────────────
# 主面板
# ─────────────────────────────────────────────────────────────

class CompPanel(QWidget):
    """阵容详情面板（340px 宽）。"""

    PANEL_W = 340

    # 变体阵容「导入」按钮触发，携带 unit dict 列表
    variant_import_requested = pyqtSignal(list)

    def __init__(self, manager: DataManager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.cache   = ImageCache.instance()
        self._comp: Composition | None = None
        self._extra_emblems: list[str] = []

        self.setFixedWidth(self.PANEL_W)
        self.setStyleSheet(f"background: {BG_SECTION}; color: {TEXT_PRI};")

        self._build_ui()
        self._populate_selector()
        self._show_comp(self.manager.get_comps_sorted()[0] if manager.is_loaded else None)

    # ──────────────────────────────────────────────────────────
    # 构建骨架
    # ──────────────────────────────────────────────────────────

    def _build_ui(self):
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(0)

        # ── 顶栏：下拉 + 统计 ─────────────────────────────────
        top = QWidget()
        top.setStyleSheet(f"background:{BG_SECTION}; padding: 6px 10px;")
        top_lay = QHBoxLayout(top)
        top_lay.setContentsMargins(10, 6, 10, 6)
        top_lay.setSpacing(8)

        self._combo = QComboBox()
        self._combo.setFixedHeight(28)
        self._combo.setStyleSheet(f"""
            QComboBox {{
                background: #1e2736;
                border: 1px solid {BORDER};
                border-radius: 4px;
                color: {TEXT_PRI};
                font-size: 12px;
                font-weight: 600;
                padding: 0 8px;
            }}
            QComboBox::drop-down {{ border: none; width: 20px; }}
            QComboBox::down-arrow {{ width: 0; height: 0; }}
            QComboBox QAbstractItemView {{
                background: #1a2030;
                border: 1px solid {BORDER};
                color: {TEXT_PRI};
                selection-background-color: #2a3a52;
                outline: none;
            }}
        """)
        self._combo.currentIndexChanged.connect(self._on_combo_changed)
        top_lay.addWidget(self._combo, stretch=1)

        self._lbl_placement = _label("—", TEXT_GOLD, 11, bold=True)
        self._lbl_winrate   = _label("—", TEXT_SEC,  10)
        top_lay.addWidget(self._lbl_placement)
        top_lay.addWidget(self._lbl_winrate)
        self._root.addWidget(top)

        self._traits_divider = _hline()
        self._root.addWidget(self._traits_divider)

        # ── 英雄卡片网格 ───────────────────────────────────────
        self._units_widget = QWidget()
        self._units_widget.setStyleSheet(f"background:{BG_SECTION};")
        self._units_grid = QGridLayout(self._units_widget)
        self._units_grid.setContentsMargins(10, 10, 10, 10)
        self._units_grid.setSpacing(4)
        self._root.addWidget(self._units_widget)

        # ── 进阶信息（动态替换，默认折叠）─────────────────────
        self._advanced_host = QWidget()
        self._advanced_host.setStyleSheet(f"background:{BG_SECTION};")
        self._advanced_lay = QVBoxLayout(self._advanced_host)
        self._advanced_lay.setContentsMargins(0, 0, 0, 0)
        self._advanced_lay.setSpacing(0)
        self._root.addWidget(self._advanced_host)
        self._advanced_host.hide()

        self._root.addWidget(_hline())

        # ── 激活羁绊区 ────────────────────────────────────────
        self._traits_widget = QWidget()
        self._traits_widget.setStyleSheet(f"background:{BG_SECTION};")
        traits_lay = QVBoxLayout(self._traits_widget)
        traits_lay.setContentsMargins(10, 8, 10, 8)
        traits_lay.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)
        title = _label("已激活羁绊", TEXT_PRI, 10, bold=True)
        self._traits_hint = _label("", TEXT_SEC, 9)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self._traits_hint)
        traits_lay.addLayout(header)

        self._traits_grid_host = QWidget()
        self._traits_grid = QGridLayout(self._traits_grid_host)
        self._traits_grid.setContentsMargins(0, 0, 0, 0)
        self._traits_grid.setHorizontalSpacing(6)
        self._traits_grid.setVerticalSpacing(6)
        traits_lay.addWidget(self._traits_grid_host)

        self._root.addWidget(self._traits_widget)
        self._traits_divider.hide()
        self._traits_widget.hide()

        # ── 进阶信息 / 变体区块（动态替换）────────────────────
        self._advanced_widget: AdvancedInfoSection | None = None
        self._variants_widget: VariantsSection | None = None

    # ──────────────────────────────────────────────────────────
    # 填充下拉列表
    # ──────────────────────────────────────────────────────────

    def _populate_selector(self):
        self._combo.blockSignals(True)
        self._combo.clear()
        for c in self.manager.get_comps_sorted():
            cost_str = f"★{c.cost}" if c.cost else ""
            label    = f"{c.name}  {cost_str}"
            self._combo.addItem(label, userData=c.slug)
        self._combo.blockSignals(False)

    def _on_combo_changed(self, idx: int):
        slug = self._combo.itemData(idx)
        if slug:
            self._show_comp(self.manager.get_comp(slug))

    # ──────────────────────────────────────────────────────────
    # 渲染阵容
    # ──────────────────────────────────────────────────────────

    def _show_comp(self, comp: Composition | None):
        if comp is None:
            return
        self._comp = comp

        self._render_stats(comp)
        self._render_units(comp)
        self._render_advanced(comp)
        self._render_variants(comp)

        # 预载所有图片
        icons = [u.icon for u in comp.units if u.icon]
        for u in comp.units:
            for b in u.builds:
                icons += [i.icon for i in b.items if i.icon]
        # 变体英雄头像
        for v in comp.variants:
            icons += [vu.icon for vu in v.units if vu.icon]
        # 进阶信息中的装备/携带者
        for emblem in comp.emblems:
            if emblem.get("icon"):
                icons.append(emblem["icon"])
            icons += [c.get("icon", "") for c in emblem.get("carriers", []) if c.get("icon")]
        for item in comp.special_items:
            if item.get("icon"):
                icons.append(item["icon"])
            carrier = item.get("carrier") or {}
            if carrier.get("icon"):
                icons.append(carrier["icon"])
            for bi in (item.get("best_build") or {}).get("items", []):
                if bi.get("icon"):
                    icons.append(bi["icon"])
        icons += [u.get("icon", "") for u in comp.unit_stats if u.get("icon")]
        self.cache.prefetch(icons)

    def _render_stats(self, comp: Composition):
        self._lbl_placement.setText(f"★ {comp.placement_str}")
        self._lbl_winrate.setText(f"胜率 {comp.win_rate_pct}")

    def _render_units(self, comp: Composition):
        while self._units_grid.count():
            item = self._units_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        from ui.widgets.unit_card import UnitCard
        cols = 5
        for i, unit in enumerate(comp.units):
            card = UnitCard(unit, self.cache)
            self._units_grid.addWidget(card, i // cols, i % cols)

    def _render_traits(self, comp: Composition):
        # 羁绊展示已迁移到 PickListPanel，这里保留空实现以兼容旧调用。
        return

    def _render_advanced(self, comp: Composition):
        if self._advanced_widget:
            self._advanced_lay.removeWidget(self._advanced_widget)
            self._advanced_widget.deleteLater()
            self._advanced_widget = None

        has_info = any([
            comp.emblems,
            comp.special_items,
            comp.unit_stats,
        ])
        self._advanced_host.setVisible(has_info)
        if not has_info:
            return

        self._advanced_widget = AdvancedInfoSection(comp, self.cache)
        self._advanced_lay.addWidget(self._advanced_widget)

    def _compute_active_traits(self, comp: Composition) -> list[dict]:
        counts: Counter[str] = Counter()
        for unit in comp.units:
            for trait_id in self.manager.get_unit_traits(unit.id):
                counts[trait_id] += 1
        for trait_id in self._extra_emblems:
            counts[trait_id] += 1

        active_traits = []
        for trait_id, count in counts.items():
            thresholds = self.manager.get_trait_thresholds(trait_id)
            active_threshold = 0
            active_tier = 0
            for idx, threshold in enumerate(thresholds, 1):
                if count >= threshold:
                    active_threshold = threshold
                    active_tier = idx
            if thresholds and active_threshold == 0:
                continue
            name = self.manager.get_trait_name(trait_id)
            if active_threshold:
                label = f"{name} {count}/{active_threshold}"
                tooltip = f"{name}：当前 {count}，已激活第 {active_tier} 档"
            else:
                label = f"{name} {count}"
                tooltip = f"{name}：当前 {count}"
            active_traits.append({
                "id": trait_id,
                "name": name,
                "icon": self.manager.get_trait_info(trait_id).get("icon", ""),
                "count": count,
                "active_threshold": active_threshold,
                "active_tier": active_tier,
                "label": label,
                "subtitle": f"{count}/{active_threshold}" if active_threshold else f"{count}",
                "tooltip": tooltip,
            })

        active_traits.sort(
            key=lambda x: (-x["active_threshold"], -x["count"], x["name"])
        )
        return active_traits

    def _render_variants(self, comp: Composition):
        if self._variants_widget:
            self._root.removeWidget(self._variants_widget)
            self._variants_widget.deleteLater()
            self._variants_widget = None

        if comp.variants:
            self._variants_widget = VariantsSection(comp.variants, self.cache)
            # 透传到 CompPanel 级别，供 overlay 连线到 PickListPanel
            self._variants_widget.import_requested.connect(
                self.variant_import_requested
            )
            self._root.addWidget(self._variants_widget)

    # ──────────────────────────────────────────────────────────
    # 外部接口
    # ──────────────────────────────────────────────────────────

    def refresh_data(self):
        """数据更新后重新填充（由 DataManager 回调触发）。"""
        self._populate_selector()
        if self._comp:
            updated = self.manager.get_comp(self._comp.slug)
            self._show_comp(updated or self.manager.get_comps_sorted()[0])

    def set_extra_emblems(self, trait_ids: list[str]):
        self._extra_emblems = list(trait_ids)
