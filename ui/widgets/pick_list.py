"""
TFT Assistant — 自动拿牌控制面板
==================================
布局（嵌入 overlay，340px 宽）：

  ┌─────────────────────────────────────────┐
  │  自动拿牌  [开关]  [选区]  [状态文字]   │
  ├─────────────────────────────────────────┤
  │ [头像][头像][头像][头像][头像]           │  ← 拿取列表（10格）
  │ [头像][头像][头像][ + ][ + ]            │    已选→头像，空→+号
  ├─────────────────────────────────────────┤
  │ [从当前阵容导入]                        │
  └─────────────────────────────────────────┘
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QRect, QPoint
from PyQt6.QtGui import (
    QColor, QFont, QPainter, QPainterPath, QPixmap, QPen, QBrush, QCursor,
    QKeySequence, QShortcut,
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFrame,
)

from bot.auto_picker import AutoPicker
from bot.region_selector import RegionConfig, RegionSelector, RegionPreviewer
from data.manager import DataManager
from ui.image_cache import ImageCache
from ui.widgets.hero_selector import HeroSelectorDialog

# ── 调色板 ────────────────────────────────────────────────────
BG_SECTION  = "#141922"
BG_SLOT     = "#1e2736"
BG_HOVER    = "#2a3a52"
BORDER      = "#252d3d"
TEXT_PRI    = "#e2e8f0"
TEXT_SEC    = "#7a8a9e"
TEXT_GOLD   = "#c89b3c"
GREEN       = "#52c07a"
RED         = "#e05252"
COST_COLORS = {1:"#5d6168",2:"#2a7a36",3:"#1a5fa8",4:"#8b3fa8",5:"#c89b3c"}

SLOT_COUNT  = 10
SLOT_SZ     = 46      # 每个格子的像素大小
BADGE_SZ    = 13


def _hline() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet(f"color:{BORDER}; background:{BORDER};")
    f.setFixedHeight(1)
    return f


def _btn(text: str, color: str = TEXT_SEC, bg: str = "#1e2736",
         bold: bool = False) -> QPushButton:
    b = QPushButton(text)
    b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
    w = "600" if bold else "400"
    b.setStyleSheet(f"""
        QPushButton {{
            background:{bg}; border:1px solid {BORDER};
            color:{color}; font-size:10px; font-weight:{w};
            border-radius:4px; padding:3px 8px;
        }}
        QPushButton:hover {{ background:{BG_HOVER}; color:{TEXT_PRI}; }}
        QPushButton:pressed {{ background:#1a2030; }}
    """)
    return b


# ─────────────────────────────────────────────────────────────
# 单个拿取格子 Widget
# ─────────────────────────────────────────────────────────────

class _PickSlot(QWidget):
    """
    一个 46×46 的格子：
      - 空状态：显示 + 号，点击弹出英雄选择器
      - 已填：显示英雄头像，点击移除
    """

    def __init__(self, slot_idx: int, parent_panel: "PickListPanel"):
        super().__init__()
        self._idx    = slot_idx
        self._panel  = parent_panel
        self._hero_id:   str | None = None
        self._hero_name: str = ""
        self._hero_cost: int = 1
        self._icon:      str = ""
        self._px:        QPixmap | None = None

        self.setFixedSize(SLOT_SZ, SLOT_SZ)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setToolTip("")

        parent_panel.cache.image_ready.connect(self._on_ready)

    # ── 数据 ──────────────────────────────────────────────────

    def set_hero(self, hero_id: str, name: str, cost: int, icon: str):
        self._hero_id   = hero_id
        self._hero_name = name
        self._hero_cost = cost
        self._icon      = icon
        self._px        = self._panel.cache.get(icon) if icon else None
        self.setToolTip(f"{name}（点击移除）")
        self.update()

    def clear(self):
        self._hero_id   = None
        self._hero_name = ""
        self._hero_cost = 1
        self._icon      = ""
        self._px        = None
        self.setToolTip("")
        self.update()

    def is_empty(self) -> bool:
        return self._hero_id is None

    def _on_ready(self, path: str, px: QPixmap):
        if path == self._icon:
            self._px = px
            self.update()

    # ── 交互 ──────────────────────────────────────────────────

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if self.is_empty():
            self._panel.open_hero_selector(self._idx, self.mapToGlobal(QPoint(0, SLOT_SZ)))
        else:
            self._panel.remove_slot(self._idx)

    # ── 绘制 ──────────────────────────────────────────────────

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = 5

        if self.is_empty():
            self._draw_empty(p, r)
        else:
            self._draw_hero(p, r)
        p.end()

    def _draw_empty(self, p: QPainter, r: int):
        p.setBrush(QBrush(QColor(BG_SLOT)))
        p.setPen(QPen(QColor(BORDER), 1, Qt.PenStyle.DashLine))
        p.drawRoundedRect(1, 1, SLOT_SZ-2, SLOT_SZ-2, r, r)

        p.setPen(QColor(TEXT_SEC))
        f = QFont(); f.setPointSize(18); f.setWeight(QFont.Weight.Light)
        p.setFont(f)
        p.drawText(QRect(0, 0, SLOT_SZ, SLOT_SZ), Qt.AlignmentFlag.AlignCenter, "+")

    def _draw_hero(self, p: QPainter, r: int):
        border = QColor(COST_COLORS.get(self._hero_cost, "#5d6168"))

        # 圆角裁剪头像
        clip = QPainterPath()
        clip.addRoundedRect(0, 0, SLOT_SZ, SLOT_SZ, r, r)
        p.setClipPath(clip)

        if self._px:
            src  = self._px
            side = min(src.width(), src.height())
            sx   = (src.width() - side) // 2
            sy   = (src.height() - side) // 2
            p.drawPixmap(QRect(0, 0, SLOT_SZ, SLOT_SZ),
                         src, QRect(sx, sy, side, side))
        else:
            p.fillRect(0, 0, SLOT_SZ, SLOT_SZ, QColor("#1e2433"))

        # 名字覆盖条
        p.fillRect(0, 0, SLOT_SZ, 14, QColor(0, 0, 0, 150))

        p.setClipping(False)
        p.setPen(QPen(border, 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(1, 1, SLOT_SZ-2, SLOT_SZ-2, r, r)

        # 英雄名
        p.setPen(QColor(TEXT_PRI))
        f = QFont(); f.setPointSize(6); f.setBold(True)
        p.setFont(f)
        metrics = p.fontMetrics()
        name = metrics.elidedText(self._hero_name, Qt.TextElideMode.ElideRight, SLOT_SZ - 2)
        p.drawText(QRect(0, 0, SLOT_SZ, 14), Qt.AlignmentFlag.AlignCenter, name)

        # 费用徽章
        bsz = BADGE_SZ
        p.setBrush(QBrush(border))
        p.setPen(QPen(QColor("#0a0c10"), 1))
        p.drawRoundedRect(SLOT_SZ-bsz, SLOT_SZ-bsz, bsz, bsz, bsz//2, bsz//2)
        p.setPen(QColor("white"))
        f2 = QFont(); f2.setPointSize(6); f2.setBold(True)
        p.setFont(f2)
        p.drawText(QRect(SLOT_SZ-bsz, SLOT_SZ-bsz, bsz, bsz),
                   Qt.AlignmentFlag.AlignCenter, str(self._hero_cost))


# ─────────────────────────────────────────────────────────────
# 主面板
# ─────────────────────────────────────────────────────────────

class PickListPanel(QWidget):
    """自动拿牌区域（嵌入 overlay 底部）。"""

    def __init__(self, manager: DataManager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.cache   = ImageCache.instance()
        self.picker  = AutoPicker.instance()

        # 拿取列表：slot_idx → {id, name, cost, icon}
        self._slots: dict[int, dict] = {}

        # 英雄选择弹窗（懒加载）
        self._hero_dlg: HeroSelectorDialog | None = None

        self.setStyleSheet(f"background:{BG_SECTION};")
        self._build_ui()
        self._connect_picker()
        self._load_region_config()

    # ──────────────────────────────────────────────────────────
    # 构建 UI
    # ──────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(_hline())

        # ── 控制栏 ────────────────────────────────────────────
        ctrl = QWidget()
        ctrl.setStyleSheet(f"background:{BG_SECTION};")
        c_lay = QHBoxLayout(ctrl)
        c_lay.setContentsMargins(10, 7, 10, 7)
        c_lay.setSpacing(6)

        lbl = QLabel("自动拿牌")
        lbl.setStyleSheet(f"color:{TEXT_PRI}; font-size:11px; font-weight:600;"
                          f" background:transparent;")
        c_lay.addWidget(lbl)

        self._toggle_btn = _btn("▶ 开启", GREEN, bold=True)
        self._toggle_btn.setFixedWidth(68)
        self._toggle_btn.clicked.connect(self._on_toggle)
        c_lay.addWidget(self._toggle_btn)

        self._region_btn = _btn("⊞ 选区", TEXT_SEC)
        self._region_btn.clicked.connect(self._on_select_region)
        c_lay.addWidget(self._region_btn)

        self._preview_btn = _btn("👁 校验", TEXT_SEC)
        self._preview_btn.clicked.connect(self._on_preview_region)
        c_lay.addWidget(self._preview_btn)

        clear_btn = _btn("✕ 清除", RED)
        clear_btn.clicked.connect(self._clear_all)
        c_lay.addWidget(clear_btn)

        c_lay.addStretch()

        self._status_lbl = QLabel("未设置区域")
        self._status_lbl.setStyleSheet(
            f"color:{TEXT_SEC}; font-size:9px; background:transparent;")
        c_lay.addWidget(self._status_lbl)

        root.addWidget(ctrl)
        root.addWidget(_hline())

        # ── 10 格拿取列表 ─────────────────────────────────────
        grid_wrap = QWidget()
        grid_wrap.setStyleSheet(f"background:{BG_SECTION};")
        grid_lay = QGridLayout(grid_wrap)
        grid_lay.setContentsMargins(10, 8, 10, 8)
        grid_lay.setSpacing(5)

        self._slot_widgets: list[_PickSlot] = []
        cols = 5
        for i in range(SLOT_COUNT):
            slot = _PickSlot(i, self)
            self._slot_widgets.append(slot)
            grid_lay.addWidget(slot, i // cols, i % cols)

        root.addWidget(grid_wrap)
        root.addWidget(_hline())

        # ── 阵容导入按钮 ──────────────────────────────────────
        import_row = QWidget()
        import_row.setStyleSheet(f"background:{BG_SECTION};")
        i_lay = QHBoxLayout(import_row)
        i_lay.setContentsMargins(10, 6, 10, 6)

        import_btn = _btn("⚡ 从当前阵容导入", TEXT_GOLD)
        import_btn.clicked.connect(self._import_from_comp)
        i_lay.addWidget(import_btn)
        i_lay.addStretch()

        root.addWidget(import_row)

        # ── 快捷键 ────────────────────────────────────────────
        sc = QShortcut(QKeySequence("Ctrl+A"), self.window() or self)
        sc.activated.connect(self._on_toggle)

    # ──────────────────────────────────────────────────────────
    # 信号连接
    # ──────────────────────────────────────────────────────────

    def _connect_picker(self):
        self.picker.status_changed.connect(self._on_status_changed)
        self.picker.hero_picked.connect(self._on_hero_picked)
        self.picker.loading_changed.connect(self._on_loading_changed)

    def _on_status_changed(self, msg: str):
        self._status_lbl.setText(msg)
        running = self.picker.is_running()
        loading = self.picker.is_loading()
        self._toggle_btn.setText("⏳ 加载中" if loading else ("■ 停止" if running else "▶ 开启"))
        color = RED if running else GREEN
        self._toggle_btn.setStyleSheet(self._toggle_btn.styleSheet().replace(
            "color:" + (GREEN if running else RED), "color:" + color
        ))
        self._toggle_btn.setEnabled(not loading)

    def _on_loading_changed(self, loading: bool):
        self._toggle_btn.setEnabled(not loading)
        if loading:
            self._toggle_btn.setText("⏳ 加载中")
        else:
            running = self.picker.is_running()
            self._toggle_btn.setText("■ 停止" if running else "▶ 开启")

    def _on_hero_picked(self, hero_id: str):
        # 可加闪光动画，目前仅 log
        pass

    # ──────────────────────────────────────────────────────────
    # 区域配置
    # ──────────────────────────────────────────────────────────

    def _load_region_config(self):
        cfg = RegionConfig.load()
        if cfg and cfg.is_valid():
            self.picker.set_region_config(cfg)
            self._status_lbl.setText("区域已设置  •  未开启")

    def _on_select_region(self):
        """启动全屏选区 UI。"""
        # 先隐藏 overlay 避免遮挡游戏画面
        win = self.window()
        if win:
            win.hide()

        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()

        sel = RegionSelector()
        sel.run()

        if win:
            win.show()

        if sel.config:
            self.picker.set_region_config(sel.config)
            self._status_lbl.setText("区域已更新  •  未开启")

    def _on_preview_region(self):
        """把当前保存的区域直接叠加到桌面上，便于肉眼检查漂移。"""
        cfg = RegionConfig.load()
        if not cfg or not cfg.is_valid():
            self._status_lbl.setText("⚠ 暂无可校验区域")
            return

        win = self.window()
        if win:
            win.hide()

        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()

        RegionPreviewer(cfg).run()

        if win:
            win.show()
        self._status_lbl.setText("区域校验完成  •  未开启")

    # ──────────────────────────────────────────────────────────
    # 拿取列表管理
    # ──────────────────────────────────────────────────────────

    def _current_pick_ids(self) -> set[str]:
        return {v["id"] for v in self._slots.values()}

    def open_hero_selector(self, slot_idx: int, pos: QPoint):
        """打开英雄选择弹窗（从空格子点击触发）。"""
        # 每次都重建弹窗，避免 disconnect() 在无连接时 crash
        if self._hero_dlg is not None:
            self._hero_dlg.close()
            self._hero_dlg.deleteLater()

        picks = self._current_pick_ids()
        self._hero_dlg = HeroSelectorDialog(
            self.manager, self.cache, picks,
            parent=self.window(),
        )
        self._hero_dlg.hero_selected.connect(
            lambda hid, si=slot_idx: self._assign_hero(si, hid)
        )
        self._hero_dlg.show_near(pos)

    def _assign_hero(self, slot_idx: int, hero_id: str):
        """将英雄分配到指定格子。"""
        # 若已在其他格子则先移除
        for idx, info in list(self._slots.items()):
            if info["id"] == hero_id and idx != slot_idx:
                self._slot_widgets[idx].clear()
                del self._slots[idx]

        # 读取英雄信息
        info = self._get_hero_info(hero_id)
        if not info:
            return

        self._slots[slot_idx] = info
        self._slot_widgets[slot_idx].set_hero(
            info["id"], info["name"], info["cost"], info["icon"]
        )
        self._sync_picker()

    def remove_slot(self, slot_idx: int):
        if slot_idx in self._slots:
            del self._slots[slot_idx]
        self._slot_widgets[slot_idx].clear()
        self._sync_picker()

    def _sync_picker(self):
        """将当前拿取列表同步到 AutoPicker。"""
        self.picker.set_pick_list(self._current_pick_ids())

    def _get_hero_info(self, hero_id: str) -> dict | None:
        import json
        from config import RAW_DATA_DIR
        path = RAW_DATA_DIR / "entity_units.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        info = data.get(hero_id)
        if not info:
            return None
        return {
            "id":   hero_id,
            "name": info.get("name", hero_id),
            "cost": info.get("cost", 1),
            "icon": info.get("icon", ""),
        }

    # ──────────────────────────────────────────────────────────
    # 阵容导入
    # ──────────────────────────────────────────────────────────

    def _import_from_comp(self):
        """将当前 CompPanel 选中阵容的英雄导入拿取列表（最多 10 个）。"""
        comp_panel = self._find_comp_panel()
        if not comp_panel or not comp_panel._comp:
            return
        units = [
            {"id": u.id, "name": u.name, "cost": u.cost or 1, "icon": u.icon}
            for u in comp_panel._comp.units
        ]
        self.import_units(units)

    def import_units(self, units: list[dict]):
        """
        将给定的英雄列表导入拿取格子（清空后填入，最多 10 个）。
        units: [{"id", "name", "cost", "icon"}, ...]
        由「从当前阵容导入」和「变体阵容导入」共同调用。
        """
        # 清空
        for i in range(SLOT_COUNT):
            self._slot_widgets[i].clear()
        self._slots.clear()

        for idx, info in enumerate(units[:SLOT_COUNT]):
            self._slots[idx] = info
            self._slot_widgets[idx].set_hero(
                info["id"], info["name"], info.get("cost", 1), info.get("icon", "")
            )

        self._sync_picker()

    def _find_comp_panel(self):
        """向上遍历找到 overlay 中的 CompPanel 实例。"""
        from ui.widgets.comp_panel import CompPanel
        win = self.window()
        if not win:
            return None
        for child in win.findChildren(CompPanel):
            return child
        return None

    # ──────────────────────────────────────────────────────────
    # 开关
    # ──────────────────────────────────────────────────────────

    def _clear_all(self):
        """清空所有拿取格子。"""
        for i in range(SLOT_COUNT):
            self._slot_widgets[i].clear()
        self._slots.clear()
        self._sync_picker()

    def _on_toggle(self):
        if self.picker.is_loading():
            self._status_lbl.setText("⏳ OCR 正在加载，请稍候…")
            return
        self.picker.toggle()
