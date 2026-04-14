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

from PyQt6.QtCore import Qt, QRect, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap, QPen, QBrush, QCursor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QFrame, QGridLayout,
    QSizePolicy, QPushButton,
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
            left.setFixedWidth(34)
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

        self._root.addWidget(_hline())

        # ── 英雄卡片网格 ───────────────────────────────────────
        self._units_widget = QWidget()
        self._units_widget.setStyleSheet(f"background:{BG_SECTION};")
        self._units_grid = QGridLayout(self._units_widget)
        self._units_grid.setContentsMargins(10, 10, 10, 10)
        self._units_grid.setSpacing(4)
        self._root.addWidget(self._units_widget)

        # ── 变体区块（动态替换）───────────────────────────────
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
        self._render_variants(comp)

        # 预载所有图片
        icons = [u.icon for u in comp.units if u.icon]
        for u in comp.units:
            for b in u.builds[:1]:
                icons += [i.icon for i in b.items if i.icon]
        # 变体英雄头像
        for v in comp.variants:
            icons += [vu.icon for vu in v.units if vu.icon]
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
