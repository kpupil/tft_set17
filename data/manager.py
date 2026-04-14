"""
TFT Assistant — 数据管理器
==========================
DataManager 是 data 层的统一对外接口，UI 和 Bot 模块只与它交互。

只暴露阵容相关 API，不暴露英雄/装备/羁绊的原始实体查询
（实体数据仅在合并阶段内部使用，已融入 Composition 对象中）。

典型用法：
    from data.manager import DataManager

    dm = DataManager()
    dm.load()                        # 从缓存加载，不联网
    dm.refresh()                     # 爬取 + 合并，更新数据
    dm.refresh(async_mode=True,
               on_done=callback)     # 后台更新，不阻塞 UI

    comps = dm.get_comps_sorted()    # 按名次排序
    comps = dm.search_comp("暗星烬") # 模糊搜索
    comp  = dm.get_comp("dark_star_jhin")
    comps = dm.filter_comps(max_cost=3, max_placement=4.0)
    comps = dm.get_comps_with_unit("TFT17_Jhin")  # 供 bot 使用
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Callable, Optional

from config import PROCESSED_DIR, RAW_DATA_DIR, MERGER
from data.models import Composition
from data.scraper import TFTableScraper
from data.merger import TFTDataMerger

logger = logging.getLogger("tft.manager")


class DataManager:
    """
    TFT 阵容数据管理器（线程安全）。
    refresh() 支持后台线程运行，load() 可在任意线程调用。
    """

    def __init__(
        self,
        raw_dir:       Path = RAW_DATA_DIR,
        processed_dir: Path = PROCESSED_DIR,
        lang:          str  = "zh",
    ):
        self.raw_dir       = Path(raw_dir)
        self.processed_dir = Path(processed_dir)
        self.lang          = lang

        self._comps: dict[str, Composition] = {}   # slug → Composition

        self._loaded = False
        self._refreshing = False
        self._lock   = threading.Lock()
        self._callbacks: list[Callable[[], None]] = []

    # ──────────────────────────────────────────────────────────
    # 加载（从本地缓存，不联网）
    # ──────────────────────────────────────────────────────────

    def load(self) -> bool:
        """
        从 processed/merged_comps.json 加载阵容数据。
        返回 True 表示加载成功。
        """
        with self._lock:
            return self._load_internal()

    def _load_internal(self) -> bool:
        path = self.processed_dir / MERGER["output_filename"]
        if not path.exists():
            logger.warning("缓存不存在，请先运行 dm.refresh()")
            self._loaded = False
            return False

        raw = json.loads(path.read_text(encoding="utf-8"))
        self._comps  = {slug: Composition.from_dict(d) for slug, d in raw.items()}
        self._loaded = bool(self._comps)
        if self._loaded:
            logger.info("已加载 %d 个阵容", len(self._comps))
        return self._loaded

    # ──────────────────────────────────────────────────────────
    # 刷新（爬取 → 合并 → 重新加载）
    # ──────────────────────────────────────────────────────────

    def refresh(
        self,
        force:      bool                        = False,
        async_mode: bool                        = False,
        on_done:    Optional[Callable[[], None]] = None,
    ) -> bool:
        """
        爬取最新数据并重新合并。

        Args:
            force:      True 时忽略缓存，强制重新抓取所有阵容详情
            async_mode: True 时在后台线程运行，不阻塞 UI
            on_done:    完成后的回调（async_mode=True 时有用）

        Returns:
            True 表示已启动刷新；False 表示已有刷新任务在执行，本次跳过。
        """
        def _do():
            try:
                logger.info("启动爬虫 …")
                scraper = TFTableScraper(lang=self.lang, output_dir=self.raw_dir)
                scraper.fetch_all(force=force)
                scraper.save()

                logger.info("启动合并 …")
                TFTDataMerger(
                    raw_dir=self.raw_dir,
                    processed_dir=self.processed_dir,
                    lang=self.lang,
                ).merge()

                with self._lock:
                    self._load_internal()
                self._notify_callbacks()
                if on_done:
                    on_done()
            except Exception as exc:
                logger.exception("数据刷新失败: %s", exc)
            finally:
                with self._lock:
                    self._refreshing = False

        with self._lock:
            if self._refreshing:
                logger.info("刷新任务已在执行，跳过重复请求")
                return False
            self._refreshing = True

        if async_mode:
            threading.Thread(target=_do, name="tft-refresh", daemon=True).start()
        else:
            _do()
        return True

    # ──────────────────────────────────────────────────────────
    # 回调（供 UI 订阅数据更新事件）
    # ──────────────────────────────────────────────────────────

    def on_data_updated(self, callback: Callable[[], None]):
        """注册数据更新回调，每次 refresh 完成后触发。"""
        self._callbacks.append(callback)

    def _notify_callbacks(self):
        for cb in self._callbacks:
            try:
                cb()
            except Exception as exc:
                logger.warning("回调执行失败: %s", exc)

    # ──────────────────────────────────────────────────────────
    # 阵容查询 API
    # ──────────────────────────────────────────────────────────

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def is_refreshing(self) -> bool:
        return self._refreshing

    @property
    def comp_count(self) -> int:
        return len(self._comps)

    def get_comp(self, slug: str) -> Optional[Composition]:
        """通过 slug 精确获取阵容。"""
        return self._comps.get(slug)

    def get_comps_sorted(
        self,
        by:    str           = "avg_placement",  # "avg_placement" | "win_rate"
        top_n: Optional[int] = None,
    ) -> list[Composition]:
        """
        返回排序后的阵容列表。
        by="avg_placement" → 升序（名次低 = 强）
        by="win_rate"      → 降序（胜率高 = 强）
        """
        comps = list(self._comps.values())
        if by == "win_rate":
            comps.sort(key=lambda c: c.win_rate, reverse=True)
        else:
            comps.sort(key=lambda c: c.avg_placement)
        return comps[:top_n] if top_n else comps

    def search_comp(self, keyword: str) -> list[Composition]:
        """
        按中文名/英文名/slug 模糊搜索阵容，
        结果按 avg_placement 升序排列。
        """
        kw = keyword.strip().lower()
        if not kw:
            return self.get_comps_sorted()
        results = [
            c for c in self._comps.values()
            if kw in c.name.lower()
            or kw in c.name_en.lower()
            or kw in c.slug.lower()
        ]
        results.sort(key=lambda c: c.avg_placement)
        return results

    def filter_comps(
        self,
        max_cost:      Optional[int]   = None,   # 费用评级上限
        max_placement: Optional[float] = None,   # 平均名次上限
        min_win_rate:  Optional[float] = None,   # 胜率下限（0.0–1.0）
        with_unit:     Optional[str]   = None,   # 必须包含该英雄 ID
    ) -> list[Composition]:
        """多条件过滤，结果按 avg_placement 升序排列。"""
        results = list(self._comps.values())
        if max_cost is not None:
            results = [c for c in results if c.cost is not None and c.cost <= max_cost]
        if max_placement is not None:
            results = [c for c in results if c.avg_placement <= max_placement]
        if min_win_rate is not None:
            results = [c for c in results if c.win_rate >= min_win_rate]
        if with_unit is not None:
            results = [c for c in results if c.get_unit(with_unit) is not None]
        results.sort(key=lambda c: c.avg_placement)
        return results

    def get_comps_with_unit(self, unit_id: str) -> list[Composition]:
        """
        返回所有包含某英雄的阵容，按 avg_placement 升序。
        供 bot 模块判断"场上出现了某英雄，应该走哪个阵容"。
        """
        return sorted(
            [c for c in self._comps.values() if c.get_unit(unit_id) is not None],
            key=lambda c: c.avg_placement,
        )

    def summary(self) -> dict:
        return {"compositions": len(self._comps), "loaded": self._loaded}
