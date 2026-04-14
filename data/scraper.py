"""
TFT Assistant — 数据爬虫
========================
从 tftable.cc 抓取 TFT 阵容详情数据。

只抓取助手所需的内容：
  - composition_cards.json   阵容列表（名次/胜率/费用）
  - entity_units.json        英雄名称/费用（ID 解析用）
  - entity_items.json        装备名称（ID 解析用）
  - entity_traits.json       羁绊名称（ID 解析用）
  - item_recipes.json        装备合成配方（散件计算用）
  - compositions/{slug}.json 每个阵容的完整详情

并发优化：
  - 阵容详情使用 ThreadPoolExecutor 并发抓取（默认 5 线程）
  - 每个线程独立 Session，互不干扰
  - 增量模式：已缓存的阵容直接跳过，无需重复请求

用法（CLI）：
    python -m data.scraper              # 全量抓取
    python -m data.scraper --force      # 强制重新抓取（忽略缓存）
    python -m data.scraper --lang en    # 英文数据
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import re
import threading
import time
from json import JSONDecodeError
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin

import requests

from config import SCRAPER, RAW_DATA_DIR

logger = logging.getLogger("tft.scraper")


class TFTableScraper:
    """
    从 tftable.cc 抓取阵容数据。
    调用 fetch_all() 后再调用 save() 写入 cache/raw/。
    """

    def __init__(
        self,
        lang:       str  = SCRAPER["default_lang"],
        output_dir: Path = RAW_DATA_DIR,
    ):
        cfg = SCRAPER
        self.lang       = lang if lang in cfg["supported_langs"] else cfg["default_lang"]
        self.output_dir = Path(output_dir)
        self.base_url   = cfg["base_url"]

        # 主线程用的共享 Session（仅用于非并发请求）
        self._session = requests.Session()
        self._session.headers.update(cfg["headers"])

        self._timeout   = cfg["timeout"]
        self._delay_sec = cfg["request_delay"]
        self._retries   = cfg["max_retries"]
        self._workers   = cfg["workers"]
        self._detail_cache_max_age_hours = cfg.get("detail_cache_max_age_hours", 24)

        # 内部缓存
        self._build_id: Optional[str]  = None
        self._manifest: Optional[dict] = None

        # 抓取结果
        self.composition_cards:   list = []
        self.composition_details: dict = {}
        self.item_recipes:        dict = {}
        self.entity_units:        dict = {}
        self.entity_items:        dict = {}
        self.entity_traits:       dict = {}

    # ──────────────────────────────────────────────────────────
    # HTTP 工具（主线程用）
    # ──────────────────────────────────────────────────────────

    def _get(self, url: str, expect_json: bool = True) -> Optional[Any]:
        """带重试的 GET 请求（主线程，使用共享 Session）。"""
        full_url = url if url.startswith("http") else urljoin(self.base_url, url)
        for attempt in range(1, self._retries + 1):
            try:
                resp = self._session.get(full_url, timeout=self._timeout)
                resp.raise_for_status()
                return resp.json() if expect_json else resp.text
            except requests.exceptions.RequestException as exc:
                logger.warning("请求失败 (%d/%d): %s — %s", attempt, self._retries, full_url, exc)
                if attempt < self._retries:
                    time.sleep(self._delay_sec * attempt)
        logger.error("请求最终失败: %s", full_url)
        return None

    def _delay(self):
        time.sleep(self._delay_sec)

    def _is_detail_cache_fresh(self, path: Path) -> bool:
        """根据 mtime 判断阵容详情缓存是否仍可复用。"""
        if not path.exists():
            return False
        max_age_hours = self._detail_cache_max_age_hours
        if max_age_hours is None or max_age_hours <= 0:
            return False
        age_seconds = time.time() - path.stat().st_mtime
        return age_seconds < max_age_hours * 3600

    # ──────────────────────────────────────────────────────────
    # Next.js buildId & Manifest
    # ──────────────────────────────────────────────────────────

    def get_build_id(self) -> Optional[str]:
        """从首页 __NEXT_DATA__ 提取 buildId。"""
        if self._build_id:
            return self._build_id
        logger.info("获取 buildId …")
        html = self._get("/", expect_json=False)
        if not html:
            return None
        match = re.search(r'"buildId"\s*:\s*"([^"]+)"', html)
        if match:
            self._build_id = match.group(1)
            logger.info("buildId: %s", self._build_id)
            return self._build_id
        logger.error("无法提取 buildId")
        return None

    def get_manifest(self) -> dict:
        """获取数据文件索引。"""
        if self._manifest:
            return self._manifest
        url = f"/{self.lang}/__shared/manifest.json"
        data = self._get(url)
        self._manifest = data or {}
        if data:
            logger.info("Manifest OK，%d 个文件引用", len(data))
        return self._manifest

    def _resolve_path(self, key: str) -> Optional[str]:
        m = self.get_manifest()
        path = m.get(key)
        if not path:
            logger.warning("Manifest 找不到 key: %s", key)
            return None
        return path if path.startswith("/") else f"/{self.lang}/__shared/{path}"

    # ──────────────────────────────────────────────────────────
    # 抓取：阵容卡片 & 实体数据（顺序，量少）
    # ──────────────────────────────────────────────────────────

    def fetch_composition_cards(self) -> list:
        path = self._resolve_path("composition-cards")
        if not path:
            return []
        logger.info("获取阵容卡片 …")
        data = self._get(path)
        self._delay()
        if data and "cards" in data:
            self.composition_cards = data["cards"]
            logger.info("  共 %d 个阵容", len(self.composition_cards))
        return self.composition_cards

    def fetch_item_recipes(self) -> dict:
        path = self._resolve_path("item-recipes")
        if not path:
            return {}
        logger.info("获取装备配方 …")
        data = self._get(path)
        self._delay()
        if data and "itemRecipes" in data:
            self.item_recipes = data["itemRecipes"]
            logger.info("  共 %d 个配方", len(self.item_recipes))
        return self.item_recipes

    def fetch_entity_units(self) -> dict:
        path = self._resolve_path("entity-units")
        if not path:
            return {}
        logger.info("获取英雄数据 …")
        data = self._get(path)
        self._delay()
        if data:
            self.entity_units = data
            logger.info("  共 %d 个英雄", len(data))
        return self.entity_units

    def fetch_entity_items(self) -> dict:
        path = self._resolve_path("entity-items")
        if not path:
            return {}
        logger.info("获取装备数据 …")
        data = self._get(path)
        self._delay()
        if data:
            self.entity_items = data
            logger.info("  共 %d 件装备", len(data))
        return self.entity_items

    def fetch_entity_traits(self) -> dict:
        path = self._resolve_path("entity-traits")
        if not path:
            return {}
        logger.info("获取羁绊数据 …")
        data = self._get(path)
        self._delay()
        if data:
            self.entity_traits = data
            logger.info("  共 %d 个羁绊", len(data))
        return self.entity_traits

    # ──────────────────────────────────────────────────────────
    # 并发抓取：阵容详情（核心优化）
    # ──────────────────────────────────────────────────────────

    def _make_session(self) -> requests.Session:
        """为每个 worker 线程创建独立 Session。"""
        s = requests.Session()
        s.headers.update(SCRAPER["headers"])
        return s

    def _fetch_detail_worker(self, slug: str, build_id: str) -> Optional[dict]:
        """
        单个 worker 的抓取逻辑（独立 Session，线程安全）。
        每个阵容需要 2 次 HTTP 请求：
          1. /_next/data/{buildId}/{slug}.json  → 阵容结构 + detailPath
          2. detailPath                          → 英雄优先级矩阵
        """
        session = self._make_session()
        try:
            # ── 请求 1：SSG 数据 ───────────────────────────────
            url1 = urljoin(self.base_url, f"/_next/data/{build_id}/{slug}.json")
            for attempt in range(1, self._retries + 1):
                try:
                    r = session.get(url1, timeout=self._timeout)
                    r.raise_for_status()
                    data1 = r.json()
                    break
                except requests.exceptions.RequestException as exc:
                    if attempt < self._retries:
                        time.sleep(self._delay_sec * attempt)
                    else:
                        logger.warning("  [失败] %s 请求1: %s", slug, exc)
                        return None

            if not data1 or "pageProps" not in data1:
                logger.warning("  [跳过] %s: pageProps 缺失", slug)
                return None

            page_props   = data1["pageProps"]
            composition  = page_props.get("composition", {})
            detail_path  = page_props.get("detailPath")

            # ── 请求 2：优先级详情 ────────────────────────────
            details = None
            if detail_path:
                time.sleep(self._delay_sec)
                detail_url = detail_path if detail_path.startswith("http") \
                             else urljoin(self.base_url, detail_path)
                for attempt in range(1, self._retries + 1):
                    try:
                        r2 = session.get(detail_url, timeout=self._timeout)
                        r2.raise_for_status()
                        details = r2.json()
                        break
                    except requests.exceptions.RequestException as exc:
                        if attempt < self._retries:
                            time.sleep(self._delay_sec * attempt)
                        else:
                            logger.warning("  [失败] %s 请求2: %s", slug, exc)

            return {"slug": slug, "composition": composition, "details": details}

        finally:
            session.close()

    def fetch_all_composition_details(self, force: bool = False):
        """
        并发抓取所有阵容详情。

        Args:
            force: True 时忽略缓存，全量重新抓取；
                   False 时跳过 output_dir/compositions/ 中已有的文件（增量）。
        """
        if not self.composition_cards:
            self.fetch_composition_cards()

        build_id = self.get_build_id()
        if not build_id:
            logger.error("无法获取 buildId，跳过阵容详情")
            return

        comp_cache_dir = self.output_dir / "compositions"

        # ── 分拣：缓存命中 vs 需要抓取 ────────────────────────
        pending: list[dict] = []
        cached_count = 0
        stale_count = 0
        for card in self.composition_cards:
            slug = card.get("slug")
            if not slug:
                continue
            cached_file = comp_cache_dir / f"{slug}.json"
            if force:
                pending.append(card)
                continue
            if self._is_detail_cache_fresh(cached_file):
                try:
                    # 直接从缓存读取，不占用网络
                    self.composition_details[slug] = json.loads(
                        cached_file.read_text(encoding="utf-8")
                    )
                    cached_count += 1
                    continue
                except (OSError, JSONDecodeError) as exc:
                    logger.warning("  [重抓] %s 缓存读取失败: %s", slug, exc)
            elif cached_file.exists():
                stale_count += 1
            pending.append(card)

        if cached_count:
            logger.info("  缓存命中 %d 个阵容，跳过", cached_count)
        if stale_count:
            logger.info(
                "  %d 个阵容缓存已超过 %d 小时，重新抓取",
                stale_count,
                self._detail_cache_max_age_hours,
            )

        if not pending:
            logger.info("所有阵容已有缓存，无需抓取")
            return

        total   = len(pending)
        done    = 0
        counter_lock = threading.Lock()

        logger.info("并发抓取 %d 个阵容详情（%d 线程）…", total, self._workers)

        def _task(card: dict) -> tuple[str, Optional[dict]]:
            nonlocal done
            slug   = card["slug"]
            result = self._fetch_detail_worker(slug, build_id)
            with counter_lock:
                done += 1
                name = card.get("display_name_cn", slug)
                status = "✓" if result else "✗"
                logger.info("  [%d/%d] %s %s", done, total, status, name)
            return slug, result

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self._workers,
            thread_name_prefix="tft-detail",
        ) as executor:
            for slug, result in executor.map(_task, pending):
                if result:
                    self.composition_details[slug] = result

        success = len([v for v in self.composition_details.values() if v])
        logger.info(
            "阵容详情完成: %d 成功 / %d 失败",
            success,
            total - (success - cached_count),
        )

    # ──────────────────────────────────────────────────────────
    # 全量抓取
    # ──────────────────────────────────────────────────────────

    def fetch_all(self, force: bool = False):
        """
        全量抓取入口。
        force=True 时忽略本地缓存，重新抓取所有阵容详情。
        """
        logger.info("=" * 55)
        logger.info("开始抓取 | 语言: %s | 并发: %d 线程 | 强制: %s",
                    self.lang, self._workers, force)
        logger.info("=" * 55)

        self.get_build_id()
        self.get_manifest()

        # 顺序抓取（量少，无需并发）
        self.fetch_composition_cards()
        self.fetch_item_recipes()
        self.fetch_entity_units()
        self.fetch_entity_items()
        self.fetch_entity_traits()

        # 并发抓取阵容详情
        self.fetch_all_composition_details(force=force)

        logger.info("=" * 55)
        self._log_summary()

    def _log_summary(self):
        logger.info("抓取完成：")
        logger.info("  阵容卡片: %d  |  阵容详情: %d",
                    len(self.composition_cards), len(self.composition_details))
        logger.info("  英雄: %d  |  装备: %d  |  羁绊: %d  |  配方: %d",
                    len(self.entity_units), len(self.entity_items),
                    len(self.entity_traits), len(self.item_recipes))

    # ──────────────────────────────────────────────────────────
    # 保存到 cache/raw/
    # ──────────────────────────────────────────────────────────

    def save(self, output_dir: Optional[Path] = None):
        """
        保存抓取结果。目录结构：
            raw/
              composition_cards.json
              item_recipes.json
              entity_units.json
              entity_items.json
              entity_traits.json
              compositions/{slug}.json
        """
        out = Path(output_dir) if output_dir else self.output_dir
        out.mkdir(parents=True, exist_ok=True)

        plain_files = {
            "composition_cards.json": self.composition_cards,
            "item_recipes.json":      self.item_recipes,
            "entity_units.json":      self.entity_units,
            "entity_items.json":      self.entity_items,
            "entity_traits.json":     self.entity_traits,
        }

        for fname, data in plain_files.items():
            if data:
                (out / fname).write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                logger.info("  已保存: %s", fname)

        if self.composition_details:
            comp_dir = out / "compositions"
            comp_dir.mkdir(exist_ok=True)
            for slug, detail in self.composition_details.items():
                (comp_dir / f"{slug}.json").write_text(
                    json.dumps(detail, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            logger.info("  已保存 %d 个阵容详情 → compositions/",
                        len(self.composition_details))

        logger.info("数据已保存至: %s", out.resolve())


# ─────────────────────────────────────────────────────────────
# CLI 入口
# ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="TFT Assistant — 数据爬虫")
    parser.add_argument("--lang",    default=SCRAPER["default_lang"],
                        choices=SCRAPER["supported_langs"])
    parser.add_argument("--output",  default=None, help="输出目录（默认: data/cache/raw）")
    parser.add_argument("--force",   action="store_true", help="忽略缓存，重新抓取所有详情")
    parser.add_argument("--workers", type=int, default=None, help="并发线程数（默认: config.workers）")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")

    out_dir = Path(args.output) if args.output else RAW_DATA_DIR
    scraper = TFTableScraper(lang=args.lang, output_dir=out_dir)
    if args.workers:
        scraper._workers = args.workers
    scraper.fetch_all(force=args.force)
    scraper.save()


if __name__ == "__main__":
    main()
