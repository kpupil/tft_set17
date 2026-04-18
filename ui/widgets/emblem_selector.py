"""
TFT Assistant — 转职选择弹窗
==============================
展示当前赛季可用的纹章羁绊，点击后将其加入待选转职列表。
"""

from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from data.manager import DataManager
from ui.image_cache import ImageCache
from ui.widgets.trait_badge import CompactTraitChip

BG = "#141922"
BG_TAB = "#1a2230"
BG_HOVER = "#252d3d"
BORDER = "#252d3d"
TEXT_PRI = "#e2e8f0"
TEXT_SEC = "#7a8a9e"
TEXT_GOLD = "#c89b3c"


class EmblemSelectorDialog(QWidget):
    """转职选择弹窗。"""

    emblem_selected = pyqtSignal(str)  # trait_id

    def __init__(self, manager: DataManager, selected_traits: set[str], parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self._manager = manager
        self._cache = ImageCache.instance()
        self._selected_traits = set(selected_traits)
        self.setFixedWidth(340)
        self.setStyleSheet(
            f"background:{BG}; border:1px solid {BORDER}; border-radius:6px;"
        )
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        header = QHBoxLayout()
        title = QLabel("选择转职")
        title.setStyleSheet(
            f"color:{TEXT_PRI}; font-size:11px; font-weight:600; background:transparent;"
        )
        hint = QLabel("点击添加，重复点击可在主面板移除")
        hint.setStyleSheet(
            f"color:{TEXT_SEC}; font-size:9px; background:transparent;"
        )
        header.addWidget(title)
        header.addStretch()
        header.addWidget(hint)
        lay.addLayout(header)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color:{BORDER};")
        lay.addWidget(line)

        grid_wrap = QWidget()
        grid = QGridLayout(grid_wrap)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)

        for i, emblem in enumerate(self._manager.get_emblem_traits()):
            trait_id = emblem["trait_id"]
            thresholds = emblem.get("thresholds") or []
            active_threshold = thresholds[0] if thresholds else 0
            card = CompactTraitChip(
                trait_id=trait_id,
                name=emblem["name"],
                icon=emblem.get("icon", ""),
                current_count=active_threshold or 1,
                active=True,
                active_threshold=active_threshold,
                is_emblem=True,
                removable=False,
                clickable=True,
                cache=self._cache,
                tooltip=f'{emblem["name"]}纹章',
            )
            card.clicked.connect(self._select)
            grid.addWidget(card, i // 4, i % 4)

        lay.addWidget(grid_wrap)

    def _select(self, trait_id: str):
        self.emblem_selected.emit(trait_id)
        self.close()

    def show_near(self, pos: QPoint):
        self.adjustSize()
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = min(max(pos.x(), geo.left() + 8), geo.right() - self.width() - 8)
            y = min(max(pos.y(), geo.top() + 8), geo.bottom() - self.height() - 8)
            pos = QPoint(x, y)
        self.move(pos)
        self.show()
        self.raise_()
