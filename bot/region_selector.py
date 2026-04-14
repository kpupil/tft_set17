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

    @staticmethod
    def load() -> Optional["RegionConfig"]:
        if REGION_CONFIG_PATH.exists():
            try:
                d = json.loads(REGION_CONFIG_PATH.read_text(encoding="utf-8"))
                return RegionConfig(
                    ocr_rects=d.get("ocr_rects", []),
                    click_points=d.get("click_points", []),
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

        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)
        self.show()
        self.activateWindow()
        self.raise_()

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
        cfg = RegionConfig(
            ocr_rects=[
                [r.x(), r.y(), r.width(), r.height()]
                for r in ocr_rects
            ],
            click_points=[
                [p.x(), p.y()]
                for p in click_points
            ],
        )
        cfg.save()
        self.config = cfg
        self._done  = True

    def _on_cancel(self):
        self.config = None
        self._done  = True
