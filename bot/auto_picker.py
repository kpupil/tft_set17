"""
TFT Assistant — 自动拿牌
========================
在 QThread 中运行拿牌主循环：
    截图 → OCR 识别 → 匹配拿取列表 → pyautogui 点击购买

公开接口：
    picker = AutoPicker.instance()
    picker.set_pick_list({"TFT17_Jhin", "TFT17_Lux"})
    picker.start()
    picker.stop()

信号：
    picker.status_changed(str)   ← UI 状态文字（"运行中"/"已停止"/错误信息）
    picker.hero_picked(str)      ← 成功购买了某英雄 id
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from typing import Optional, Set

from PyQt6.QtCore import QThread, pyqtSignal, QMutex, QMutexLocker

from bot.region_selector import RegionConfig
from bot.ocr_engine import OCREngine
from config import BOT

logger = logging.getLogger("tft.picker")

POLL_INTERVAL = BOT.get("scan_interval_ms", 500) / 1000   # 一轮扫描的目标总间隔（秒）
CLICK_DELAY   = BOT.get("pick_delay_ms", 200) / 1000      # 每次点击后等待（秒，防连点）


class AutoPicker(QThread):
    """
    自动拿牌线程。
    通过 start()/stop() 控制，通过 set_pick_list() 更新目标英雄。
    """

    status_changed = pyqtSignal(str)
    hero_picked    = pyqtSignal(str)   # hero_id
    loading_changed = pyqtSignal(bool)

    _instance: "AutoPicker | None" = None
    _platform_warned = False

    @classmethod
    def instance(cls) -> "AutoPicker":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running   = False
        self._mutex     = QMutex()
        self._pick_set: Set[str] = set()
        self._config:   Optional[RegionConfig] = None
        self._ocr       = OCREngine.instance()
        self._loading   = False

    # ──────────────────────────────────────────────────────────
    # 配置
    # ──────────────────────────────────────────────────────────

    def set_region_config(self, config: RegionConfig):
        with QMutexLocker(self._mutex):
            self._config = config

    def set_pick_list(self, hero_ids: Set[str]):
        with QMutexLocker(self._mutex):
            self._pick_set = set(hero_ids)
        logger.info("拿取列表更新: %s", self._pick_set)

    def is_running(self) -> bool:
        return self._running

    def is_loading(self) -> bool:
        with QMutexLocker(self._mutex):
            return self._loading

    def is_ready(self) -> bool:
        return self._ocr.is_loaded()

    # ──────────────────────────────────────────────────────────
    # 控制
    # ──────────────────────────────────────────────────────────

    def prewarm_ocr(self):
        """在后台预热 OCR，避免首次开启时长时间阻塞。"""
        with QMutexLocker(self._mutex):
            if self._loading or self._ocr.is_loaded():
                return
            self._loading = True
        self.loading_changed.emit(True)
        self.status_changed.emit("⏳ OCR 预热中…")
        threading.Thread(
            target=self._prewarm_worker,
            name="tft-ocr-prewarm",
            daemon=True,
        ).start()

    def start_picking(self):
        """开始自动拿牌（如果条件满足）。"""
        with QMutexLocker(self._mutex):
            config = self._config
            pick   = self._pick_set

        if not config or not config.is_valid():
            self.status_changed.emit("⚠ 请先设置商店区域")
            return
        if not pick:
            self.status_changed.emit("⚠ 拿取列表为空")
            return
        if self.is_loading():
            self.status_changed.emit("⏳ OCR 正在加载，请稍候…")
            return

        if not self.isRunning():
            self._running = True
            self.start()
            if self._ocr.is_loaded():
                self.status_changed.emit("▶ 自动拿牌运行中")
            else:
                self._set_loading_state(True)
                self.status_changed.emit("⏳ OCR 加载中…")

    def stop_picking(self):
        """停止自动拿牌。"""
        if self.is_loading():
            self.status_changed.emit("⏳ OCR 加载中，暂不可切换")
            return
        self._running = False
        self.status_changed.emit("■ 自动拿牌已停止")

    def toggle(self):
        if self._running:
            self.stop_picking()
        else:
            self.start_picking()

    # ──────────────────────────────────────────────────────────
    # 主循环（QThread.run）
    # ──────────────────────────────────────────────────────────

    def run(self):
        logger.info("自动拿牌线程启动")

        # 确保 OCR 引擎已加载（首次较慢）
        try:
            self._ensure_ocr_loaded()
        except Exception as e:
            self.status_changed.emit(f"❌ OCR 加载失败: {e}")
            self._running = False
            return

        if not self._running:
            logger.info("自动拿牌线程退出")
            return

        self.status_changed.emit("▶ 自动拿牌运行中")

        while self._running:
            tick_started = time.perf_counter()
            try:
                self._tick()
            except Exception as e:
                logger.exception("拿牌循环异常: %s", e)
                self.status_changed.emit(f"❌ 运行错误: {e}")
                self._running = False
                break
            elapsed = time.perf_counter() - tick_started
            sleep_s = max(0.0, POLL_INTERVAL - elapsed)
            if sleep_s > 0:
                time.sleep(sleep_s)

        logger.info("自动拿牌线程退出")

    def _prewarm_worker(self):
        try:
            self._ocr.load()
            self.status_changed.emit("OCR 已预热  •  可随时开启")
        except Exception as e:
            logger.exception("OCR 预热失败: %s", e)
            self.status_changed.emit(f"❌ OCR 预热失败: {e}")
        finally:
            self._set_loading_state(False)

    def _ensure_ocr_loaded(self):
        if self._ocr.is_loaded():
            return
        self._set_loading_state(True)
        try:
            self._ocr.load()
        finally:
            self._set_loading_state(False)

    def _set_loading_state(self, value: bool):
        with QMutexLocker(self._mutex):
            self._loading = value
        self.loading_changed.emit(value)

    def _tick(self):
        """单次轮询：截图 → 识别 → 点击。"""
        with QMutexLocker(self._mutex):
            config   = self._config
            pick_set = set(self._pick_set)

        if not config or not pick_set:
            return

        ocr_rects = self._ocr.resolve_native_ocr_rects(config)
        if len(ocr_rects) != 5:
            logger.warning("区域配置无效：OCR 区域数量异常")
            return

        details = self._ocr.recognize_all_details(ocr_rects)
        results = [(d["hero_id"], d["score"]) for d in details]
        self._log_ocr_results(details, pick_set)

        for slot_idx, (hero_id, score) in enumerate(results):
            if hero_id and hero_id in pick_set:
                logger.info(
                    "识别到目标英雄: %s (slot %d, score %.2f) → 点击购买",
                    hero_id, slot_idx + 1, score,
                )
                self._click_slot(config, slot_idx)
                self.hero_picked.emit(hero_id)
                time.sleep(CLICK_DELAY)

    @staticmethod
    def _log_ocr_results(details: list[dict], pick_set: Set[str]):
        if not details:
            logger.info("本轮 OCR 无识别结果")
            return

        slot_logs = []
        for idx, detail in enumerate(details, start=1):
            raw_text = detail.get("raw_text") or "-"
            hero_id = detail.get("hero_id") or "-"
            score = detail.get("score", 0.0)
            elapsed_ms = detail.get("elapsed_ms", 0.0)
            preprocess_ms = detail.get("preprocess_ms", 0.0)
            infer_ms = detail.get("infer_ms", 0.0)
            match_ms = detail.get("match_ms", 0.0)
            screenshot_ms = detail.get("screenshot_ms", 0.0)
            target_flag = "TARGET" if detail.get("hero_id") in pick_set else "MISS"
            slot_logs.append(
                f"S{idx}: raw='{raw_text}' -> {hero_id} "
                f"({score:.2f}, total={elapsed_ms:.0f}ms, shot={screenshot_ms:.0f}ms, "
                f"prep={preprocess_ms:.0f}ms, infer={infer_ms:.0f}ms, match={match_ms:.0f}ms, "
                f"{target_flag})"
            )

        logger.info("本轮 OCR 结果 | %s", " | ".join(slot_logs))

    def _click_slot(self, config: RegionConfig, slot_idx: int):
        """通过 pydirectinput 点击指定 slot 的购买位置。"""
        try:
            click_points = self._ocr.resolve_native_click_points(config)
            x, y = click_points[slot_idx]
            self._perform_click(x, y)
            logger.info("已点击 slot %d 坐标 (%d, %d)", slot_idx + 1, x, y)
        except ImportError:
            logger.error("缺少依赖: pip install pydirectinput")
        except IndexError:
            logger.error("无效的 slot_idx: %d", slot_idx)

    def _perform_click(self, x: int, y: int):
        """
        执行一次“移动到目标点 + 按下 + 抬起”点击流程。
        使用 pydirectinput（更容易被 DirectX 游戏接收）。
        说明：pydirectinput 为纯 Python 包，Windows 32/64 位均可运行。
        """
        if sys.platform != "win32":
            if not self._platform_warned:
                self._platform_warned = True
                logger.warning("pydirectinput 当前仅支持 Windows；已跳过自动点击")
            return

        import pydirectinput

        pydirectinput.moveTo(x, y)
        time.sleep(0.01)
        pydirectinput.mouseDown(button="left")
        pydirectinput.mouseUp(button="left")
