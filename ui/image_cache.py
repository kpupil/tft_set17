"""
TFT Assistant — 图片缓存
========================
异步下载并缓存英雄头像 / 装备图标到本地。
使用 QThread + signal 机制，下载完成后通知 widget 刷新。

用法：
    cache = ImageCache()
    cache.image_ready.connect(my_slot)    # 订阅更新
    px = cache.get("/set17/avatar-webp/TFT17_Jhin.webp?v=2")
    # 返回 None 则还在下载中，等 image_ready 信号
"""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from typing import Optional

import requests
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QPixmap

from config import IMAGE_DIR, SCRAPER

BASE_URL      = SCRAPER["base_url"]
PLACEHOLDER_W = 48
PLACEHOLDER_H = 48


class ImageCache(QObject):
    """
    全局图片缓存（单例模式）。
    - get(icon_path) 立即返回 QPixmap 或 None
    - 未缓存时后台下载，完成后发射 image_ready(icon_path, pixmap)
    """
    image_ready = pyqtSignal(str, QPixmap)   # (icon_path, pixmap)

    _instance: Optional["ImageCache"] = None

    @classmethod
    def instance(cls) -> "ImageCache":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        super().__init__()
        IMAGE_DIR.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._in_flight: set[str] = set()

    # ──────────────────────────────────────────────────────────
    # 公共 API
    # ──────────────────────────────────────────────────────────

    def get(self, icon_path: str) -> Optional[QPixmap]:
        """
        返回缓存 QPixmap，如未缓存则触发后台下载并返回 None。
        调用方应订阅 image_ready 信号，在收到信号后刷新显示。
        """
        if not icon_path:
            return None

        cache_file = self._cache_path(icon_path)
        if cache_file.exists():
            px = QPixmap(str(cache_file))
            return px if not px.isNull() else None

        # 触发后台下载
        with self._lock:
            if icon_path not in self._in_flight:
                self._in_flight.add(icon_path)
                t = threading.Thread(
                    target=self._download,
                    args=(icon_path, cache_file),
                    daemon=True,
                )
                t.start()
        return None

    def prefetch(self, icon_paths: list[str]):
        """批量预下载（不等待）。"""
        for p in icon_paths:
            self.get(p)

    # ──────────────────────────────────────────────────────────
    # 内部
    # ──────────────────────────────────────────────────────────

    def _cache_path(self, icon_path: str) -> Path:
        key = hashlib.md5(icon_path.encode()).hexdigest()
        ext = Path(icon_path.split("?")[0]).suffix or ".webp"
        return IMAGE_DIR / f"{key}{ext}"

    def _download(self, icon_path: str, cache_file: Path):
        url = BASE_URL + icon_path
        try:
            resp = requests.get(
                url, timeout=10,
                headers={"Referer": BASE_URL, "User-Agent": SCRAPER["headers"]["User-Agent"]},
            )
            if resp.ok and resp.content:
                cache_file.write_bytes(resp.content)
                px = QPixmap()
                px.loadFromData(resp.content)
                if not px.isNull():
                    self.image_ready.emit(icon_path, px)
        except Exception:
            pass
        finally:
            with self._lock:
                self._in_flight.discard(icon_path)
