"""
TFT Assistant — 区域选择器
==========================
全屏透明遮罩，引导用户分两阶段手动标定商店区域：

  阶段 1（OCR 区域）：依次框选 5 个英雄名称所在矩形
  阶段 2（点击位置）：依次点击 5 个购买按钮中心点

结果保存到 data/cache/region_config.json，下次启动自动加载。

用法：
    from bot.region_selector import RegionSelector
    sel = RegionSelector()
    sel.run()          # 阻塞直到选区完成或取消
    config = sel.config  # 返回 RegionConfig 或 None（取消）
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QRect, QPoint, QTimer
from PyQt6.QtGui import (
    QColor, QFont, QPainter, QPainterPath, QPen, QBrush, QCursor,
    QKeySequence, QShortcut,
)
from PyQt6.QtWidgets import QApplication, QWidget, QLabel

from config import REGION_CONFIG_PATH

SLOT_COUNT = 5

# ── 配色 ──────────────────────────────────────────────────────
OVERLAY_BG   = QColor(0, 0, 0, 100)
OCR_DONE     = QColor(80, 200, 120, 160)    # 绿色：已完成的 OCR 框
OCR_DRAWING  = QColor(100, 180, 255, 180)   # 蓝色：正在画的框
CLICK_DONE   = QColor(255, 200, 60, 200)    # 黄色：已完成的点击点
CLICK_ACTIVE = QColor(255, 100, 100, 200)   # 红色：当前等待点击
TEXT_COL     = QColor(255, 255, 255, 240)
HINT_BG      = QColor(0, 0, 0, 180)


@dataclass
class RegionConfig:
    """商店区域配置，保存 5 个 OCR 区域 + 5 个点击中心。"""
    ocr_rects:     list[list[int]] = field(default_factory=list)  # [[x,y,w,h]×5]
    click_points:  list[list[int]] = field(default_factory=list)  # [[x,y]×5]
    screen_name:   str = ""
    screen_rect:   list[int] = field(default_factory=list)        # [x,y,w,h]
    ocr_rects_relative: list[list[float]] = field(default_factory=list)   # [[rx,ry,rw,rh]×5]
    click_points_relative: list[list[float]] = field(default_factory=list) # [[rx,ry]×5]

    @staticmethod
    def load() -> Optional["RegionConfig"]:
        if REGION_CONFIG_PATH.exists():
            try:
                d = json.loads(REGION_CONFIG_PATH.read_text(encoding="utf-8"))
                return RegionConfig(
                    ocr_rects=d.get("ocr_rects", []),
                    click_points=d.get("click_points", []),
                    screen_name=d.get("screen_name", ""),
                    screen_rect=d.get("screen_rect", []),
                    ocr_rects_relative=d.get("ocr_rects_relative", []),
                    click_points_relative=d.get("click_points_relative", []),
                )
            except Exception:
                return None
        return None

    def save(self):
        REGION_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        REGION_CONFIG_PATH.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def is_valid(self) -> bool:
        return (
            len(self.ocr_rects)    == SLOT_COUNT and
            len(self.click_points) == SLOT_COUNT
        )

    def _saved_screen_rect(self) -> QRect:
        if len(self.screen_rect) != 4:
            return QRect()
        x, y, w, h = self.screen_rect
        return QRect(int(x), int(y), int(w), int(h))

    def _fallback_relative_rects(self) -> list[list[float]]:
        screen = self._saved_screen_rect()
        if not screen.isValid() or screen.width() <= 0 or screen.height() <= 0:
            return []
        rels: list[list[float]] = []
        for rect in self.ocr_rects:
            if len(rect) != 4:
                continue
            x, y, w, h = rect
            rels.append([
                (x - screen.x()) / screen.width(),
                (y - screen.y()) / screen.height(),
                w / screen.width(),
                h / screen.height(),
            ])
        return rels

    def _fallback_relative_points(self) -> list[list[float]]:
        screen = self._saved_screen_rect()
        if not screen.isValid() or screen.width() <= 0 or screen.height() <= 0:
            return []
        rels: list[list[float]] = []
        for point in self.click_points:
            if len(point) != 2:
                continue
            x, y = point
            rels.append([
                (x - screen.x()) / screen.width(),
                (y - screen.y()) / screen.height(),
            ])
        return rels

    def resolved_screen_rect(self) -> QRect:
        saved = self._saved_screen_rect()
        app = QApplication.instance()
        screens = app.screens() if app else []
        if not screens:
            return saved

        if saved.isValid():
            def _score(screen) -> int:
                rect = screen.geometry()
                name_penalty = 0 if not self.screen_name or screen.name() == self.screen_name else 100_000
                size_delta = abs(rect.width() - saved.width()) + abs(rect.height() - saved.height())
                pos_delta = abs(rect.x() - saved.x()) + abs(rect.y() - saved.y())
                return name_penalty + size_delta * 10 + pos_delta

            return min(screens, key=_score).geometry()

        if self.screen_name:
            named = [screen for screen in screens if screen.name() == self.screen_name]
            if named:
                return named[0].geometry()

        active = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen() or screens[0]
        return active.geometry()

    def resolved_ocr_rects(self) -> list[list[int]]:
        return self.resolved_ocr_rects_for_target(self.resolved_screen_rect())

    def resolved_ocr_rects_for_target(self, target: QRect) -> list[list[int]]:
        rels = self.ocr_rects_relative or self._fallback_relative_rects()
        if target.isValid() and len(rels) == SLOT_COUNT:
            rects: list[list[int]] = []
            for rel in rels:
                if len(rel) != 4:
                    continue
                rx, ry, rw, rh = rel
                rects.append([
                    int(round(target.x() + rx * target.width())),
                    int(round(target.y() + ry * target.height())),
                    max(1, int(round(rw * target.width()))),
                    max(1, int(round(rh * target.height()))),
                ])
            if len(rects) == SLOT_COUNT:
                return rects
        return [[int(v) for v in rect] for rect in self.ocr_rects if len(rect) == 4]

    def resolved_click_points(self) -> list[list[int]]:
        return self.resolved_click_points_for_target(self.resolved_screen_rect())

    def resolved_click_points_for_target(self, target: QRect) -> list[list[int]]:
        rels = self.click_points_relative or self._fallback_relative_points()
        if target.isValid() and len(rels) == SLOT_COUNT:
            points: list[list[int]] = []
            for rel in rels:
                if len(rel) != 2:
                    continue
                rx, ry = rel
                points.append([
                    int(round(target.x() + rx * target.width())),
                    int(round(target.y() + ry * target.height())),
                ])
            if len(points) == SLOT_COUNT:
                return points
        return [[int(v) for v in point] for point in self.click_points if len(point) == 2]


# ─────────────────────────────────────────────────────────────
# 全屏遮罩 Widget
# ─────────────────────────────────────────────────────────────

class _SelectorOverlay(QWidget):
    """
    全屏半透明遮罩。

    阶段 1（phase='ocr'）：
        左键拖拽画矩形，松开确认；画满 5 个后自动进入阶段 2。

    阶段 2（phase='click'）：
        左键单击确认购买位置；点满 5 个后自动完成。

    ESC 取消，Z 撤销上一步。
    """

    def __init__(self, on_done, on_cancel):
        super().__init__()
        self._on_done   = on_done
        self._on_cancel = on_cancel
        self._screen_name = ""
        self._screen_rect = QRect()

        self._phase = "ocr"          # "ocr" | "click" | "done"
        self._ocr_rects:    list[QRect]  = []
        self._click_points: list[QPoint] = []

        # 拖拽状态
        self._drag_start: QPoint | None = None
        self._drag_cur:   QPoint | None = None

        self._setup_window()
        self._setup_shortcuts()

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))

        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen is None:
            raise RuntimeError("未检测到可用屏幕，无法启动区域选择器")

        self._screen_name = screen.name() or ""
        self._screen_rect = screen.geometry()
        self.setGeometry(self._screen_rect)
        self.show()
        self.activateWindow()
        self.raise_()

    @property
    def screen_name(self) -> str:
        return self._screen_name

    @property
    def screen_rect(self) -> QRect:
        return QRect(self._screen_rect)

    def _setup_shortcuts(self):
        esc = QShortcut(QKeySequence("Escape"), self)
        esc.activated.connect(self._cancel)

        undo = QShortcut(QKeySequence("Z"), self)
        undo.activated.connect(self._undo)

    # ──────────────────────────────────────────────────────────
    # 鼠标事件
    # ──────────────────────────────────────────────────────────

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if self._phase == "ocr":
            self._drag_start = e.pos()
            self._drag_cur   = e.pos()
        elif self._phase == "click":
            self._click_points.append(e.pos())
            self.update()
            if len(self._click_points) == SLOT_COUNT:
                QTimer.singleShot(300, self._finish)

    def mouseMoveEvent(self, e):
        if self._phase == "ocr" and self._drag_start:
            self._drag_cur = e.pos()
            self.update()

    def mouseReleaseEvent(self, e):
        if self._phase != "ocr" or not self._drag_start:
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return

        rect = self._make_rect(self._drag_start, e.pos())
        if rect.width() > 10 and rect.height() > 10:
            self._ocr_rects.append(rect)
            self.update()
            if len(self._ocr_rects) == SLOT_COUNT:
                QTimer.singleShot(400, self._enter_click_phase)

        self._drag_start = None
        self._drag_cur   = None

    # ──────────────────────────────────────────────────────────
    # 状态转换
    # ──────────────────────────────────────────────────────────

    def _enter_click_phase(self):
        self._phase = "click"
        self.update()

    def _finish(self):
        self._phase = "done"
        self.hide()
        self._on_done(self._ocr_rects, self._click_points)

    def _cancel(self):
        self.hide()
        self._on_cancel()

    def _undo(self):
        if self._phase == "click" and self._click_points:
            self._click_points.pop()
            self.update()
        elif self._phase == "click" and not self._click_points:
            # 撤回到 OCR 阶段最后一步
            self._phase = "ocr"
            self.update()
        elif self._phase == "ocr" and self._ocr_rects:
            self._ocr_rects.pop()
            self.update()

    # ──────────────────────────────────────────────────────────
    # 绘制
    # ──────────────────────────────────────────────────────────

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 半透明背景
        p.fillRect(self.rect(), OVERLAY_BG)

        # 已完成的 OCR 框
        for i, rect in enumerate(self._ocr_rects):
            self._draw_ocr_rect(p, rect, i + 1, done=True)

        # 正在拖拽的框
        if self._phase == "ocr" and self._drag_start and self._drag_cur:
            r = self._make_rect(self._drag_start, self._drag_cur)
            self._draw_ocr_rect(p, r, len(self._ocr_rects) + 1, done=False)

        # 已完成的点击点
        for i, pt in enumerate(self._click_points):
            self._draw_click_point(p, pt, i + 1, done=True)

        # 当前等待点击的位置提示（高亮对应 OCR 框）
        if self._phase == "click":
            idx = len(self._click_points)
            if idx < SLOT_COUNT and idx < len(self._ocr_rects):
                self._draw_ocr_rect(p, self._ocr_rects[idx], idx + 1,
                                    done=False, highlight=True)

        self._draw_hint(p)
        p.end()

    def _draw_ocr_rect(self, p: QPainter, rect: QRect, idx: int,
                       done: bool, highlight: bool = False):
        if highlight:
            color = QColor(255, 220, 0, 140)
            border = QColor(255, 200, 0, 255)
        elif done:
            color = QColor(80, 200, 120, 80)
            border = OCR_DONE
        else:
            color = QColor(100, 180, 255, 60)
            border = OCR_DRAWING

        p.fillRect(rect, QBrush(color))
        p.setPen(QPen(border, 2, Qt.PenStyle.SolidLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(rect)

        # 编号标签
        lbl_rect = QRect(rect.x(), rect.y() - 22, 60, 20)
        p.fillRect(lbl_rect, QBrush(HINT_BG))
        p.setPen(TEXT_COL)
        f = QFont(); f.setPointSize(10); f.setBold(True)
        p.setFont(f)
        p.drawText(lbl_rect, Qt.AlignmentFlag.AlignCenter,
                   f"OCR {idx}")

    def _draw_click_point(self, p: QPainter, pt: QPoint, idx: int, done: bool):
        color = CLICK_DONE if done else CLICK_ACTIVE
        p.setPen(QPen(color, 2))
        p.setBrush(QBrush(color))
        p.drawEllipse(pt, 10, 10)

        # 十字准星
        p.setPen(QPen(QColor(255, 255, 255, 200), 1))
        p.drawLine(pt.x() - 14, pt.y(), pt.x() + 14, pt.y())
        p.drawLine(pt.x(), pt.y() - 14, pt.x(), pt.y() + 14)

        # 编号
        lbl = QRect(pt.x() + 14, pt.y() - 10, 30, 20)
        p.setPen(color)
        f = QFont(); f.setPointSize(9); f.setBold(True)
        p.setFont(f)
        p.drawText(lbl, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"#{idx}")

    def _draw_hint(self, p: QPainter):
        """顶部提示条。"""
        if self._phase == "ocr":
            remaining = SLOT_COUNT - len(self._ocr_rects)
            if remaining > 0:
                msg = (f"【阶段 1/2  OCR 识别区域】  "
                       f"拖拽框选第 {len(self._ocr_rects)+1} 个英雄名称区域  "
                       f"（剩余 {remaining} 个）      Z = 撤销    ESC = 取消")
            else:
                msg = "所有 OCR 区域已标定，即将进入阶段 2…"
        elif self._phase == "click":
            remaining = SLOT_COUNT - len(self._click_points)
            if remaining > 0:
                msg = (f"【阶段 2/2  购买点击位置】  "
                       f"点击第 {len(self._click_points)+1} 个英雄的购买位置  "
                       f"（剩余 {remaining} 个）      Z = 撤销    ESC = 取消")
            else:
                msg = "全部完成！"
        else:
            msg = ""

        bar = QRect(0, 0, self.width(), 46)
        p.fillRect(bar, QBrush(HINT_BG))

        p.setPen(TEXT_COL)
        f = QFont(); f.setPointSize(13); f.setBold(True)
        p.setFont(f)
        p.drawText(bar, Qt.AlignmentFlag.AlignCenter, msg)

    # ──────────────────────────────────────────────────────────
    # 工具
    # ──────────────────────────────────────────────────────────

    @staticmethod
    def _make_rect(a: QPoint, b: QPoint) -> QRect:
        return QRect(
            min(a.x(), b.x()), min(a.y(), b.y()),
            abs(b.x() - a.x()), abs(b.y() - a.y()),
        )


class _PreviewOverlay(QWidget):
    """把当前保存的 OCR 区域和点击点直接画到桌面上，便于排查漂移。"""

    def __init__(self, config: RegionConfig, on_close):
        super().__init__()
        self._config = config
        self._on_close = on_close
        self._target_rect = config.resolved_screen_rect()
        if not self._target_rect.isValid():
            self._target_rect = self._compute_desktop_rect()
        self._setup_window()
        self._setup_shortcuts()

    def _compute_desktop_rect(self) -> QRect:
        screens = QApplication.screens()
        if not screens:
            return QRect(0, 0, 1920, 1080)
        rect = QRect(screens[0].geometry())
        for screen in screens[1:]:
            rect = rect.united(screen.geometry())
        return rect

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        self.setGeometry(self._target_rect)
        self.show()
        self.activateWindow()
        self.raise_()

    def _setup_shortcuts(self):
        esc = QShortcut(QKeySequence("Escape"), self)
        esc.activated.connect(self._close)

        enter = QShortcut(QKeySequence("Return"), self)
        enter.activated.connect(self._close)

        space = QShortcut(QKeySequence("Space"), self)
        space.activated.connect(self._close)

    def mousePressEvent(self, _e):
        self._close()

    def _close(self):
        self.hide()
        self._on_close()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 轻微暗化桌面，其余区域仍可见。
        p.fillRect(self.rect(), QColor(0, 0, 0, 72))

        for idx, rect_data in enumerate(self._config.resolved_ocr_rects(), start=1):
            if len(rect_data) != 4:
                continue
            rect = QRect(*rect_data).translated(-self._target_rect.topLeft())
            self._draw_ocr_rect(p, rect, idx)

        for idx, point_data in enumerate(self._config.resolved_click_points(), start=1):
            if len(point_data) != 2:
                continue
            pt = QPoint(*point_data) - self._target_rect.topLeft()
            self._draw_click_point(p, pt, idx)

        self._draw_hint(p)
        p.end()

    def _draw_ocr_rect(self, p: QPainter, rect: QRect, idx: int):
        fill = QColor(90, 180, 255, 50)
        border = QColor(90, 180, 255, 220)
        p.fillRect(rect, QBrush(fill))
        p.setPen(QPen(border, 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(rect)

        lbl_rect = QRect(rect.x(), rect.y() - 22, 72, 20)
        p.fillRect(lbl_rect, QBrush(HINT_BG))
        p.setPen(TEXT_COL)
        f = QFont()
        f.setPointSize(10)
        f.setBold(True)
        p.setFont(f)
        p.drawText(lbl_rect, Qt.AlignmentFlag.AlignCenter, f"OCR {idx}")

    def _draw_click_point(self, p: QPainter, pt: QPoint, idx: int):
        color = QColor(255, 180, 70, 230)
        p.setPen(QPen(color, 2))
        p.setBrush(QBrush(color))
        p.drawEllipse(pt, 10, 10)

        p.setPen(QPen(QColor(255, 255, 255, 220), 1))
        p.drawLine(pt.x() - 16, pt.y(), pt.x() + 16, pt.y())
        p.drawLine(pt.x(), pt.y() - 16, pt.x(), pt.y() + 16)

        lbl = QRect(pt.x() + 14, pt.y() - 10, 38, 20)
        p.fillRect(lbl, QBrush(HINT_BG))
        p.setPen(color)
        f = QFont()
        f.setPointSize(9)
        f.setBold(True)
        p.setFont(f)
        p.drawText(lbl, Qt.AlignmentFlag.AlignCenter, f"#{idx}")

    def _draw_hint(self, p: QPainter):
        bar = QRect(0, 0, self.width(), 54)
        p.fillRect(bar, QBrush(HINT_BG))

        p.setPen(TEXT_COL)
        f = QFont()
        f.setPointSize(12)
        f.setBold(True)
        p.setFont(f)
        label = "区域校验模式：蓝框 = OCR 区域，橙点 = 点击位置，按 ESC / Enter / 空格 或单击退出"
        p.drawText(bar, Qt.AlignmentFlag.AlignCenter, label)

        if self._config.screen_rect:
            meta = (
                f"screen={self._config.screen_name or '-'}  "
                f"saved_rect={self._config.screen_rect}  "
                f"resolved_rect={[self._target_rect.x(), self._target_rect.y(), self._target_rect.width(), self._target_rect.height()]}"
            )
            p.setPen(QColor(220, 220, 220, 220))
            f2 = QFont()
            f2.setPointSize(9)
            p.setFont(f2)
            p.drawText(
                QRect(0, 28, self.width(), 22),
                Qt.AlignmentFlag.AlignCenter,
                meta,
            )


# ─────────────────────────────────────────────────────────────
# 公开接口
# ─────────────────────────────────────────────────────────────

class RegionSelector:
    """
    启动全屏区域选择器，阻塞直到完成或取消。

    用法：
        sel = RegionSelector()
        sel.run()
        if sel.config:
            print(sel.config.ocr_rects)
    """

    def __init__(self):
        self.config: RegionConfig | None = None
        self._overlay: _SelectorOverlay | None = None
        self._done = False

    def run(self):
        """启动选区 UI（同步，内部跑 Qt 事件循环直到完成）。"""
        self._overlay = _SelectorOverlay(
            on_done=self._on_done,
            on_cancel=self._on_cancel,
        )
        # 等待完成
        while not self._done:
            QApplication.processEvents()

    def _on_done(self, ocr_rects: list[QRect], click_points: list[QPoint]):
        if self._overlay is None:
            self.config = None
            self._done = True
            return

        screen_rect = self._overlay.screen_rect
        screen_w = max(1, screen_rect.width())
        screen_h = max(1, screen_rect.height())
        cfg = RegionConfig(
            ocr_rects=[
                [
                    self._overlay.mapToGlobal(r.topLeft()).x(),
                    self._overlay.mapToGlobal(r.topLeft()).y(),
                    r.width(),
                    r.height(),
                ]
                for r in ocr_rects
            ],
            click_points=[
                [self._overlay.mapToGlobal(p).x(), self._overlay.mapToGlobal(p).y()]
                for p in click_points
            ],
            screen_name=self._overlay.screen_name,
            screen_rect=[
                screen_rect.x(),
                screen_rect.y(),
                screen_rect.width(),
                screen_rect.height(),
            ],
            ocr_rects_relative=[
                [
                    r.x() / screen_w,
                    r.y() / screen_h,
                    r.width() / screen_w,
                    r.height() / screen_h,
                ]
                for r in ocr_rects
            ],
            click_points_relative=[
                [p.x() / screen_w, p.y() / screen_h]
                for p in click_points
            ],
        )
        cfg.save()
        self.config = cfg
        self._done  = True

    def _on_cancel(self):
        self.config = None
        self._done  = True


class RegionPreviewer:
    """阻塞式区域可视化预览器，用于检查当前配置是否漂移。"""

    def __init__(self, config: RegionConfig):
        self.config = config
        self._overlay: _PreviewOverlay | None = None
        self._done = False

    def run(self):
        self._overlay = _PreviewOverlay(self.config, self._on_close)
        while not self._done:
            QApplication.processEvents()

    def _on_close(self):
        self._done = True
