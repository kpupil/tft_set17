"""
TFT Assistant — 悬浮窗口
========================
无边框、半透明、始终置顶的游戏内悬浮助手。

特性：
- 无标题栏，可拖动
- 始终置顶（游戏内可见）
- 最小化 / 关闭按钮
- 全局快捷键 Ctrl+Shift+T 切换显示/隐藏、Ctrl+Alt+Z 开关自动拿牌（不依赖窗口焦点）
- 透明背景（背后游戏画面仍可见）

启动：
    from ui.overlay import run_overlay
    run_overlay()
"""

from __future__ import annotations

import sys

from PyQt6.QtCore import Qt, QPoint, pyqtSignal, QSize, QObject, QTimer
from PyQt6.QtGui import (
    QColor, QFont,
    QPainter, QPainterPath, QBrush,
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QSizePolicy,
)

from config import UI
from data.manager import DataManager
from ui.global_hotkey import GlobalHotkeyManager
from ui.widgets.comp_panel import CompPanel
from ui.widgets.pick_list import PickListPanel

# ── 颜色 ──────────────────────────────────────────────────────
BG_WINDOW  = QColor(14, 20, 30, 230)   # 深蓝黑，90% 不透明
BG_HEADER  = QColor(10, 14, 22, 255)
BORDER_COL = QColor(37, 45, 61, 255)
TEXT_PRI   = "#e2e8f0"
TEXT_SEC   = "#7a8a9e"
GOLD       = "#c89b3c"


class DragHandle(QLabel):
    """可拖动的标题栏区域。"""

    drag_start = pyqtSignal(QPoint)
    drag_move  = pyqtSignal(QPoint)

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self._drag_pos: QPoint | None = None

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint()

    def mouseMoveEvent(self, e):
        if self._drag_pos and e.buttons() & Qt.MouseButton.LeftButton:
            delta = e.globalPosition().toPoint() - self._drag_pos
            self._drag_pos = e.globalPosition().toPoint()
            self.drag_move.emit(delta)

    def mouseReleaseEvent(self, _e):
        self._drag_pos = None


class IconButton(QPushButton):
    """小图标按钮（标题栏用）。"""
    def __init__(self, symbol: str, tooltip: str,
                 hover_color: str = "#3a4a60", parent=None):
        super().__init__(symbol, parent)
        self.setFixedSize(22, 22)
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {TEXT_SEC};
                font-size: 13px;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background: {hover_color};
                color: {TEXT_PRI};
            }}
        """)


class TFTOverlay(QMainWindow):
    """主悬浮窗口。"""

    PANEL_W = 340

    # 数据刷新完成信号（由后台线程 emit，Qt 自动 queue 到主线程执行）
    _data_refreshed = pyqtSignal()

    def __init__(self, manager: DataManager):
        super().__init__()
        self.manager = manager
        self._minimized_state = False
        self._always_on_top = bool(UI.get("always_on_top", True))

        # ── 窗口标志 ──────────────────────────────────────────
        self._apply_window_flags()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle(UI["window_title"])
        self.setFixedWidth(self.PANEL_W)

        # 最大高度：留出任务栏空间，防止窗口跑出屏幕
        screen = QApplication.primaryScreen()
        if screen:
            self.setMaximumHeight(screen.availableGeometry().height() - 80)

        self._build_ui()
        self._connect_manager()
        self._setup_hotkey()
        QTimer.singleShot(0, self._pick_panel.picker.prewarm_ocr)

    # ──────────────────────────────────────────────────────────
    # 构建 UI
    # ──────────────────────────────────────────────────────────

    def _build_ui(self):
        # 根容器（圆角绘制背景）
        self._root = _RoundedWidget(BG_WINDOW, BORDER_COL, radius=8)
        root_lay = QVBoxLayout(self._root)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)

        # ── 标题栏 ────────────────────────────────────────────
        header = QWidget()
        header.setFixedHeight(32)
        header.setStyleSheet(
            f"background: rgba(10,14,22,0.95); border-radius: 8px 8px 0 0;"
        )
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(10, 0, 6, 0)
        h_lay.setSpacing(4)

        # 圆点装饰
        for color in ("#e05252", "#e0a050", "#52c07a"):
            dot = QLabel("●")
            dot.setStyleSheet(f"color:{color}; font-size:9px; background:transparent;")
            h_lay.addWidget(dot)

        h_lay.addSpacing(4)

        drag = DragHandle("  TFT Assistant")
        drag.setStyleSheet(f"color:{TEXT_SEC}; font-size:11px; background:transparent;")
        drag.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        drag.drag_move.connect(self._on_drag)
        h_lay.addWidget(drag, stretch=1)

        # 刷新按钮
        btn_refresh = IconButton("⟳", "强制刷新最新数据")
        btn_refresh.clicked.connect(self._on_refresh)
        h_lay.addWidget(btn_refresh)

        # 置顶锁定
        self._btn_pin = IconButton("🔒", "取消置顶")
        self._btn_pin.clicked.connect(self._toggle_always_on_top)
        h_lay.addWidget(self._btn_pin)

        # 最小化
        btn_min = IconButton("—", "最小化")
        btn_min.clicked.connect(self._toggle_minimize)
        h_lay.addWidget(btn_min)

        # 关闭
        btn_close = IconButton("✕", "退出应用", hover_color="#8b2020")
        btn_close.clicked.connect(self._exit_application)
        h_lay.addWidget(btn_close)

        root_lay.addWidget(header)

        # ── 内容区（可最小化）────────────────────────────────
        self._content = QWidget()
        self._content.setStyleSheet("background:transparent;")
        content_lay = QVBoxLayout(self._content)
        content_lay.setContentsMargins(0, 0, 0, 0)
        content_lay.setSpacing(0)

        # CompPanel 直接放入布局，不用 ScrollArea
        # 这样展开变体时窗口直接向下撑开，不会出现内部滚动条
        self._panel = CompPanel(self.manager)
        content_lay.addWidget(self._panel)

        # 自动拿牌控制面板
        self._pick_panel = PickListPanel(self.manager)
        content_lay.addWidget(self._pick_panel)

        root_lay.addWidget(self._content)

        self.setCentralWidget(self._root)
        self._sync_pin_button()

        # 关键：让 QMainWindow 的内部 layout 使用 SetFixedSize 约束
        # → 内容变化时（展开/收起变体）窗口高度自动跟随，无需手动 resize
        self.layout().setSizeConstraint(
            QVBoxLayout.SizeConstraint.SetFixedSize
        )

    # ──────────────────────────────────────────────────────────
    # 事件处理
    # ──────────────────────────────────────────────────────────

    def _on_drag(self, delta: QPoint):
        self.move(self.pos() + delta)

    def _toggle_minimize(self):
        self._minimized_state = not self._minimized_state
        self._content.setVisible(not self._minimized_state)
        self.adjustSize()

    def _toggle_always_on_top(self):
        self._always_on_top = not self._always_on_top
        was_visible = self.isVisible()
        pos = self.pos()
        self._apply_window_flags()
        self._sync_pin_button()
        self.move(pos)
        if was_visible:
            self.show()
            self.raise_()

    def _on_refresh(self):
        self.manager.refresh(async_mode=True, force=True)

    def _connect_manager(self):
        # 信号连接在主线程建立 → AutoConnection → 后台 emit 时自动 queue 回主线程
        self._data_refreshed.connect(self._panel.refresh_data)
        # DataManager 的回调从后台线程触发，只 emit 信号（线程安全），不直接操作 UI
        self.manager.on_data_updated(self._data_refreshed.emit)
        # 变体阵容「导入」→ 拿牌面板
        self._panel.variant_import_requested.connect(
            self._pick_panel.import_units
        )

    def _setup_hotkey(self):
        # 全局热键：无论焦点在哪个窗口都能触发
        hk = GlobalHotkeyManager.instance()
        hk.register(
            UI.get("hotkey_toggle", "<ctrl>+<shift>+t"),
            self.toggle_visible,
        )
        hk.register(
            UI.get("hotkey_autopick", "<ctrl>+<alt>+z"),
            self._pick_panel._on_toggle,
        )
        hk.start()

    def toggle_visible(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()

    def _exit_application(self):
        app = QApplication.instance()
        if app is not None:
            app.quit()
            return
        self.close()

    def _apply_window_flags(self):
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
        )
        if self._always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)

    def _sync_pin_button(self):
        if not hasattr(self, "_btn_pin"):
            return
        self._btn_pin.setText("🔒" if self._always_on_top else "🔓")
        self._btn_pin.setToolTip("取消置顶" if self._always_on_top else "置于最上层")

    # ──────────────────────────────────────────────────────────
    # 绘制圆角背景
    # ──────────────────────────────────────────────────────────

    def closeEvent(self, event):
        GlobalHotkeyManager.instance().stop()
        event.accept()
        super().closeEvent(event)

    def paintEvent(self, _event):
        pass   # 由 _RoundedWidget 负责绘制


class _RoundedWidget(QWidget):
    """带圆角 + 深色背景的容器 Widget。"""

    def __init__(self, bg: QColor, border: QColor, radius: int = 8, parent=None):
        super().__init__(parent)
        self._bg     = bg
        self._border = border
        self._radius = radius
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        path = QPainterPath()
        path.addRoundedRect(
            0, 0, self.width() - 1, self.height() - 1,
            self._radius, self._radius,
        )
        p.fillPath(path, QBrush(self._bg))
        p.setPen(self._border)
        p.drawPath(path)
        p.end()


# ─────────────────────────────────────────────────────────────
# 启动入口
# ─────────────────────────────────────────────────────────────

def run_overlay():
    """独立启动悬浮窗（python -m ui.overlay 或 main.py ui）。"""
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setQuitOnLastWindowClosed(True)

    # 加载数据
    dm = DataManager()
    has_local_data = dm.load()
    if not has_local_data:
        print("本地数据不存在，正在拉取…（首次启动较慢）")
        dm.refresh()   # 同步，等待完成

    win = TFTOverlay(dm)
    win.show()
    if has_local_data:
        # 先用本地缓存秒开，再在后台强制抓一轮，确保每次启动都会同步最新阵容。
        QTimer.singleShot(0, lambda: dm.refresh(async_mode=True, force=True))

    sys.exit(app.exec())


if __name__ == "__main__":
    run_overlay()
