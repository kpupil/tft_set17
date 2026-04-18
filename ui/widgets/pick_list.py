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

from collections import Counter

from PyQt6.QtCore import Qt, QRect, QPoint, pyqtSignal
from PyQt6.QtGui import (
    QColor, QFont, QPainter, QPainterPath, QPixmap, QPen, QBrush, QCursor,
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFrame, QScrollArea, QApplication,
)

from bot.auto_picker import AutoPicker
from bot.region_selector import RegionConfig, RegionSelector, RegionPreviewer
from data.manager import DataManager
from ui.image_cache import ImageCache
from ui.shop_indicator_overlay import ShopIndicatorOverlay
from ui.widgets.emblem_selector import EmblemSelectorDialog
from ui.widgets.hero_selector import HeroSelectorDialog
from ui.widgets.trait_badge import CompactTraitChip, SelectedEmblemTag

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
    b.setStyleSheet(_btn_style(color=color, bg=bg, bold=bold))
    return b


def _btn_style(color: str = TEXT_SEC, bg: str = "#1e2736",
               bold: bool = False) -> str:
    w = "600" if bold else "400"
    return f"""
        QPushButton {{
            background:{bg}; border:1px solid {BORDER};
            color:{color}; font-size:10px; font-weight:{w};
            border-radius:4px; padding:3px 8px;
        }}
        QPushButton:hover {{ background:{BG_HOVER}; color:{TEXT_PRI}; }}
        QPushButton:pressed {{ background:#1a2030; }}
    """


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

    emblems_changed = pyqtSignal(list)

    def __init__(self, manager: DataManager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.cache   = ImageCache.instance()
        self.picker  = AutoPicker.instance()
        self._shop_overlay = ShopIndicatorOverlay()

        # 拿取列表：slot_idx → {id, name, cost, icon}
        self._slots: dict[int, dict] = {}
        self._selected_emblems: list[dict] = []
        self._emblem_counter = 0

        # 英雄选择弹窗（懒加载）
        self._hero_dlg: HeroSelectorDialog | None = None
        self._emblem_dlg: EmblemSelectorDialog | None = None

        self.setStyleSheet(f"background:{BG_SECTION};")
        self._build_ui()
        self._refresh_trait_chips()
        self._connect_picker()
        self._load_region_config()
        self._apply_tooltip_style()

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

        self._toggle_btn = _btn("▶ 拿牌", GREEN, bold=True)
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

        traits_wrap = QWidget()
        traits_wrap.setStyleSheet(f"background:{BG_SECTION};")
        t_lay = QVBoxLayout(traits_wrap)
        t_lay.setContentsMargins(10, 6, 10, 6)
        t_lay.setSpacing(6)

        trait_header = QHBoxLayout()
        trait_header.setContentsMargins(0, 0, 0, 0)
        trait_header.setSpacing(6)
        trait_lbl = QLabel("羁绊 / 转职")
        trait_lbl.setStyleSheet(
            f"color:{TEXT_SEC}; font-size:10px; font-weight:600; background:transparent;"
        )
        self._trait_hint_lbl = QLabel("")
        self._trait_hint_lbl.setStyleSheet(
            f"color:{TEXT_SEC}; font-size:9px; background:transparent;"
        )
        trait_header.addWidget(trait_lbl)
        self._selected_emblems_scroll = QScrollArea()
        self._selected_emblems_scroll.setWidgetResizable(True)
        self._selected_emblems_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._selected_emblems_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._selected_emblems_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._selected_emblems_scroll.setFixedHeight(26)
        self._selected_emblems_scroll.setFixedWidth(110)
        self._selected_emblems_scroll.setStyleSheet("QScrollArea { background: transparent; }")
        self._selected_emblems_host = QWidget()
        self._selected_emblems_lay = QHBoxLayout(self._selected_emblems_host)
        self._selected_emblems_lay.setContentsMargins(0, 0, 0, 0)
        self._selected_emblems_lay.setSpacing(4)
        self._selected_emblems_scroll.setWidget(self._selected_emblems_host)
        trait_header.addWidget(self._selected_emblems_scroll)
        trait_header.addStretch()
        self._add_emblem_btn = _btn("+ 转职", TEXT_GOLD)
        self._add_emblem_btn.clicked.connect(self._open_emblem_selector)
        self._add_emblem_btn.setFixedHeight(22)
        trait_header.addWidget(self._add_emblem_btn)
        trait_header.addWidget(self._trait_hint_lbl)
        t_lay.addLayout(trait_header)

        self._traits_scroll = QScrollArea()
        self._traits_scroll.setWidgetResizable(True)
        self._traits_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._traits_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._traits_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._traits_scroll.setFixedHeight(34)
        self._traits_scroll.setStyleSheet("""
            QScrollArea { background: transparent; }
            QScrollBar:horizontal {
                background: transparent;
                height: 5px;
                margin: 0;
            }
            QScrollBar::handle:horizontal {
                background: #314257;
                border-radius: 2px;
            }
            QScrollBar::add-line:horizontal,
            QScrollBar::sub-line:horizontal {
                width: 0;
            }
        """)
        self._traits_strip = QWidget()
        self._traits_strip_lay = QHBoxLayout(self._traits_strip)
        self._traits_strip_lay.setContentsMargins(0, 0, 0, 0)
        self._traits_strip_lay.setSpacing(6)
        self._traits_scroll.setWidget(self._traits_strip)
        t_lay.addWidget(self._traits_scroll)

        root.addWidget(traits_wrap)
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

        # 快捷键已移至 overlay.py 通过 GlobalHotkeyManager 全局注册
        # Ctrl+X → self._on_toggle

    def _apply_tooltip_style(self):
        app = QApplication.instance()
        if app is None:
            return
        base = app.styleSheet() or ""
        tooltip_css = """
QToolTip {
    background: #f3f6fb;
    color: #10161f;
    border: 1px solid #90a4bf;
    padding: 4px 6px;
    font-size: 10px;
}
"""
        import re
        cleaned = re.sub(r"QToolTip\s*\{[^}]*\}", "", base, flags=re.S)
        app.setStyleSheet((cleaned + "\n" + tooltip_css).strip())

    # ──────────────────────────────────────────────────────────
    # 信号连接
    # ──────────────────────────────────────────────────────────

    def _connect_picker(self):
        self.picker.status_changed.connect(self._on_status_changed)
        self.picker.hero_picked.connect(self._on_hero_picked)
        self.picker.loading_changed.connect(self._on_loading_changed)
        self.picker.shop_matches_changed.connect(self._shop_overlay.update_matches)
        self.picker.pick_enabled_changed.connect(self._update_toggle_btn)
        self._update_toggle_btn(self.picker.is_pick_enabled())

    def _on_status_changed(self, msg: str):
        self._status_lbl.setText(msg)
        self._update_toggle_btn(self.picker.is_pick_enabled())

    def _on_loading_changed(self, loading: bool):
        self._toggle_btn.setEnabled(not loading)
        if loading:
            self._toggle_btn.setText("⏳ 加载中")
        else:
            self._update_toggle_btn(self.picker.is_pick_enabled())

    def _update_toggle_btn(self, enabled: bool):
        self._toggle_btn.setText("■ 停牌" if enabled else "▶ 拿牌")
        self._toggle_btn.setStyleSheet(_btn_style(
            color=RED if enabled else GREEN,
            bold=True,
        ))
        self._toggle_btn.setEnabled(not self.picker.is_loading())

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
            self._shop_overlay.update_region_config(cfg)
            self._status_lbl.setText("区域已设置  •  商店识别待命")

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
            self._shop_overlay.update_region_config(sel.config)
            self._status_lbl.setText("区域已更新  •  商店识别待命")

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
        self._status_lbl.setText("区域校验完成  •  商店识别待命")

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
        self._refresh_trait_chips()

    def remove_slot(self, slot_idx: int):
        if slot_idx in self._slots:
            del self._slots[slot_idx]
        self._slot_widgets[slot_idx].clear()
        self._sync_picker()
        self._refresh_trait_chips()

    def _sync_picker(self):
        """将当前拿取列表同步到 AutoPicker。"""
        self.picker.set_pick_list(self._current_pick_ids())
        cfg = RegionConfig.load()
        if cfg and cfg.is_valid():
            self.picker.ensure_scanning()

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
        self._refresh_trait_chips()

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
        self._selected_emblems.clear()
        self._sync_picker()
        self._refresh_trait_chips()

    def _on_toggle(self):
        if self.picker.is_loading():
            self._status_lbl.setText("⏳ OCR 正在加载，请稍候…")
            return
        self.picker.toggle()

    def _open_emblem_selector(self):
        if self._emblem_dlg is not None:
            self._emblem_dlg.close()
            self._emblem_dlg.deleteLater()

        self._emblem_dlg = EmblemSelectorDialog(
            self.manager,
            set(),
            parent=self.window(),
        )
        self._emblem_dlg.emblem_selected.connect(self._add_emblem)
        btn_pos = self._add_emblem_btn.mapToGlobal(QPoint(0, self._add_emblem_btn.height()))
        self._emblem_dlg.show_near(btn_pos)

    def _add_emblem(self, trait_id: str):
        self._emblem_counter += 1
        self._selected_emblems.append({
            "key": f"emblem-{self._emblem_counter}",
            "trait_id": trait_id,
        })
        self._refresh_trait_chips()

    def _remove_emblem(self, emblem_key: str):
        self._selected_emblems = [
            item for item in self._selected_emblems if item["key"] != emblem_key
        ]
        self._refresh_trait_chips()

    def _refresh_trait_chips(self):
        while self._selected_emblems_lay.count():
            item = self._selected_emblems_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        while self._traits_strip_lay.count():
            item = self._traits_strip_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        emblem_map = {item["trait_id"]: item for item in self.manager.get_emblem_traits()}
        for emblem in self._selected_emblems:
            info = emblem_map.get(emblem["trait_id"], {})
            tag = SelectedEmblemTag(
                item_key=emblem["key"],
                name=info.get("name", self.manager.get_trait_name(emblem["trait_id"])),
                icon=info.get("icon", ""),
                cache=self.cache,
                tooltip=f'{info.get("name", self.manager.get_trait_name(emblem["trait_id"]))}纹章（点击移除）',
            )
            tag.clicked.connect(self._remove_emblem)
            self._selected_emblems_lay.addWidget(tag)
        self._selected_emblems_lay.addStretch()

        trait_rows = self._build_trait_rows()
        if not trait_rows:
            self._trait_hint_lbl.setText("未选择英雄")
            hint = QLabel("导入阵容或手动添加英雄后，这里会显示羁绊")
            hint.setStyleSheet(
                f"color:{TEXT_SEC}; font-size:9px; background:transparent;"
            )
            self._traits_strip_lay.addWidget(hint)
            self._traits_strip_lay.addStretch()
            return

        active_count = sum(1 for row in trait_rows if row["active"] and not row["is_emblem"])
        emblem_count = len(self._selected_emblems)
        self._trait_hint_lbl.setText(
            f"已亮 {active_count}/{len([r for r in trait_rows if not r['is_emblem']])}" +
            (f"  转职 {emblem_count}" if emblem_count else "")
        )

        for row in trait_rows:
            chip = CompactTraitChip(
                trait_id=row["id"],
                item_key=row.get("item_key", row["id"]),
                name=row["name"],
                icon=row["icon"],
                current_count=row["count"],
                active=row["active"],
                active_threshold=row["active_threshold"],
                is_emblem=row["is_emblem"],
                removable=False,
                cache=self.cache,
                tooltip=row["tooltip"],
            )
            self._traits_strip_lay.addWidget(chip)
        self._traits_strip_lay.addStretch()
        self.emblems_changed.emit([item["trait_id"] for item in self._selected_emblems])

    def _build_trait_rows(self) -> list[dict]:
        counts: Counter[str] = Counter()
        emblem_trait_ids = [item["trait_id"] for item in self._selected_emblems]
        emblem_set = set(emblem_trait_ids)
        for info in self._slots.values():
            for trait_id in self.manager.get_unit_traits(info["id"]):
                counts[trait_id] += 1
        for trait_id in emblem_trait_ids:
            counts[trait_id] += 1

        rows = []
        for trait_id, count in counts.items():
            thresholds = self.manager.get_trait_thresholds(trait_id)
            active_threshold = 0
            for threshold in thresholds:
                if count >= threshold:
                    active_threshold = threshold
            active = active_threshold > 0 or not thresholds
            name = self.manager.get_trait_name(trait_id)
            if active_threshold and active_threshold != count:
                tooltip = f"{name}：当前 {count}，实际激活档位 {active_threshold}"
            elif active:
                tooltip = f"{name}：当前 {count}，已激活"
            else:
                first = thresholds[0] if thresholds else 0
                tooltip = f"{name}：当前 {count}，距离激活还差 {max(first - count, 0)}"
            rows.append({
                "id": trait_id,
                "name": name,
                "icon": self.manager.get_trait_info(trait_id).get("icon", ""),
                "count": count,
                "active": active,
                "active_threshold": active_threshold,
                "is_emblem": trait_id in emblem_set,
                "tooltip": tooltip,
            })

        rows.sort(key=lambda row: (not row["is_emblem"], not row["active"], -row["count"], row["name"]))
        return rows
