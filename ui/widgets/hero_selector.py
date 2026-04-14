"""
TFT Assistant — 英雄选择弹窗
==============================
按费用 (1-5) 分组展示所有英雄头像，点击即选中并关闭。
已在拿取列表中的英雄显示对勾标记。

用法：
    dlg = HeroSelectorDialog(manager, cache, current_picks, parent=overlay)
    dlg.hero_selected.connect(lambda hid: ...)
    dlg.show_near(QPoint(...))
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QRect, QPoint, pyqtSignal
from PyQt6.QtGui import (
    QColor, QFont, QPainter, QPainterPath, QPixmap, QPen, QBrush, QCursor,
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFrame, QApplication,
)

from data.manager import DataManager
from ui.image_cache import ImageCache

# ── 调色板 ────────────────────────────────────────────────────
BG       = "#141922"
BG_TAB   = "#1a2230"
TAB_ACT  = "#252d3d"
BORDER   = "#252d3d"
TEXT_PRI = "#e2e8f0"
TEXT_SEC = "#7a8a9e"
COST_COLORS = {1:"#5d6168",2:"#2a7a36",3:"#1a5fa8",4:"#8b3fa8",5:"#c89b3c"}
AVATAR_SZ = 36
BADGE_SZ  = 12


class _HeroAvatar(QWidget):
    """单个英雄头像按钮（36×36）。"""

    clicked_hero = pyqtSignal(str)   # hero_id

    def __init__(self, hero_id: str, hero_name: str, cost: int,
                 icon: str, cache: ImageCache,
                 in_pick_list: bool = False, parent=None):
        super().__init__(parent)
        self._id    = hero_id
        self._name  = hero_name
        self._cost  = cost
        self._icon  = icon
        self._cache = cache
        self._in_pick = in_pick_list
        self._px: QPixmap | None = None

        self.setFixedSize(AVATAR_SZ, AVATAR_SZ)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip(hero_name)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        if icon:
            self._px = cache.get(icon)
        cache.image_ready.connect(self._on_ready)

    def _on_ready(self, path: str, px: QPixmap):
        if path == self._icon:
            self._px = px
            self.update()

    def set_in_pick(self, v: bool):
        self._in_pick = v
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked_hero.emit(self._id)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        border = QColor(COST_COLORS.get(self._cost, "#5d6168"))
        r = 4

        clip = QPainterPath()
        clip.addRoundedRect(0, 0, AVATAR_SZ, AVATAR_SZ, r, r)
        p.setClipPath(clip)

        if self._px:
            src  = self._px
            side = min(src.width(), src.height())
            sx   = (src.width() - side) // 2
            sy   = (src.height() - side) // 2
            p.drawPixmap(QRect(0, 0, AVATAR_SZ, AVATAR_SZ),
                         src, QRect(sx, sy, side, side))
        else:
            p.fillRect(0, 0, AVATAR_SZ, AVATAR_SZ, QColor("#1e2433"))

        # 已选中遮罩 + 对勾
        if self._in_pick:
            p.fillRect(0, 0, AVATAR_SZ, AVATAR_SZ, QColor(80, 200, 120, 100))
            p.setClipping(False)
            p.setPen(QPen(QColor("white"), 2))
            p.drawText(
                QRect(0, 0, AVATAR_SZ, AVATAR_SZ),
                Qt.AlignmentFlag.AlignCenter, "✓"
            )
        else:
            p.setClipping(False)

        # 边框
        p.setPen(QPen(border, 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(1, 1, AVATAR_SZ - 2, AVATAR_SZ - 2, r, r)

        # 费用徽章
        p.setBrush(QBrush(border))
        p.setPen(QPen(QColor("#0a0c10"), 1))
        p.drawRoundedRect(AVATAR_SZ - BADGE_SZ, AVATAR_SZ - BADGE_SZ,
                          BADGE_SZ, BADGE_SZ, BADGE_SZ//2, BADGE_SZ//2)
        p.setPen(QColor("white"))
        f = QFont(); f.setPointSize(6); f.setBold(True)
        p.setFont(f)
        p.drawText(QRect(AVATAR_SZ-BADGE_SZ, AVATAR_SZ-BADGE_SZ, BADGE_SZ, BADGE_SZ),
                   Qt.AlignmentFlag.AlignCenter, str(self._cost))
        p.end()


class HeroSelectorDialog(QWidget):
    """
    按费用分 Tab 的英雄选择弹窗。
    点击英雄头像发射 hero_selected(hero_id)，弹窗随之关闭。
    """

    hero_selected = pyqtSignal(str)

    def __init__(self, manager: DataManager, cache: ImageCache,
                 current_picks: set[str], parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self._manager      = manager
        self._cache        = cache
        self._current_picks = current_picks
        self._cur_cost     = 1
        self._avatar_widgets: list[_HeroAvatar] = []

        self.setFixedWidth(340)
        self.setStyleSheet(f"background:{BG}; border:1px solid {BORDER}; border-radius:6px;")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

        self._build_ui()
        self._show_cost(1)

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        # 费用 Tab 行
        tab_row = QHBoxLayout()
        tab_row.setSpacing(4)
        self._tab_btns: dict[int, QPushButton] = {}
        for cost in range(1, 6):
            btn = QPushButton(f"{cost}费")
            btn.setFixedHeight(24)
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.setCheckable(True)
            cost_c = COST_COLORS[cost]
            btn.setStyleSheet(f"""
                QPushButton {{
                    background:{BG_TAB}; border:1px solid {cost_c};
                    color:{TEXT_SEC}; border-radius:4px; font-size:10px;
                }}
                QPushButton:checked {{
                    background:{cost_c}; color:white; font-weight:bold;
                }}
                QPushButton:hover {{ background:{TAB_ACT}; color:{TEXT_PRI}; }}
            """)
            btn.clicked.connect(lambda _, c=cost: self._show_cost(c))
            self._tab_btns[cost] = btn
            tab_row.addWidget(btn)
        lay.addLayout(tab_row)

        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color:{BORDER};")
        lay.addWidget(line)

        # 英雄网格容器（动态替换）
        self._grid_container = QWidget()
        self._grid_container.setStyleSheet("background:transparent;")
        lay.addWidget(self._grid_container)

    def _show_cost(self, cost: int):
        self._cur_cost = cost

        # 更新 Tab 状态
        for c, btn in self._tab_btns.items():
            btn.setChecked(c == cost)

        # 替换旧 container（不能对同一 QWidget 反复 setLayout）
        old_container = self._grid_container
        self._grid_container = QWidget()
        self._grid_container.setStyleSheet("background:transparent;")
        self.layout().replaceWidget(old_container, self._grid_container)
        old_container.deleteLater()

        self._avatar_widgets.clear()

        # 读取该费用英雄列表
        import json
        from config import RAW_DATA_DIR
        path = RAW_DATA_DIR / "entity_units.json"
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        heroes = [(uid, info) for uid, info in data.items()
                  if info.get("cost") == cost]
        heroes.sort(key=lambda x: x[1].get("name", ""))

        grid = QGridLayout(self._grid_container)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)

        cols = 6   # 每行 6 个，留出名字的宽度
        for i, (uid, info) in enumerate(heroes):
            hero_name = info.get("name", uid)

            av = _HeroAvatar(
                hero_id=uid,
                hero_name=hero_name,
                cost=cost,
                icon=info.get("icon", ""),
                cache=self._cache,
                in_pick_list=(uid in self._current_picks),
            )
            av.clicked_hero.connect(self._on_hero_clicked)
            self._avatar_widgets.append(av)

            # 头像 + 中文名字 包装成小卡
            cell = QWidget()
            cell.setStyleSheet("background:transparent;")
            cell_lay = QVBoxLayout(cell)
            cell_lay.setContentsMargins(0, 0, 0, 0)
            cell_lay.setSpacing(2)
            cell_lay.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            cell_lay.addWidget(av, 0, Qt.AlignmentFlag.AlignHCenter)

            name_lbl = QLabel(hero_name)
            name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name_lbl.setFixedWidth(AVATAR_SZ + 4)
            name_lbl.setStyleSheet(
                f"color:{TEXT_SEC}; font-size:9px; background:transparent;"
            )
            name_lbl.setWordWrap(False)
            # 超长名字省略
            from PyQt6.QtGui import QFontMetrics
            fm = QFontMetrics(name_lbl.font())
            name_lbl.setText(fm.elidedText(
                hero_name, Qt.TextElideMode.ElideRight, AVATAR_SZ + 4
            ))
            cell_lay.addWidget(name_lbl)

            grid.addWidget(cell, i // cols, i % cols)

        self.adjustSize()

    def _on_hero_clicked(self, hero_id: str):
        self.hero_selected.emit(hero_id)
        self.hide()

    def show_near(self, global_pos: QPoint):
        """在指定位置旁边显示弹窗（自动避免超出屏幕）。"""
        self.adjustSize()
        screen = QApplication.primaryScreen().availableGeometry()
        x = min(global_pos.x(), screen.right()  - self.width())
        y = min(global_pos.y(), screen.bottom() - self.height())
        self.move(max(0, x), max(0, y))
        self.show()
        self.raise_()

    def update_picks(self, current_picks: set[str]):
        """刷新已选中状态（拿取列表变化时调用）。"""
        self._current_picks = current_picks
        for av in self._avatar_widgets:
            av.set_in_pick(av._id in current_picks)
