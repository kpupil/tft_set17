"""
TFT Assistant — 数据合并器
==========================
将爬虫抓取的原始 ID 数据（raw/）合并为人类可读的结构化数据，
输出到 cache/processed/merged_comps.json。

合并逻辑：
  1. 读取 entity_units / entity_items / entity_traits / item_recipes
  2. 遍历每个阵容卡片，加载对应的 compositions/{slug}.json
  3. 解析核心英雄、出装方案、羁绊、散件需求、变体阵容
  4. 写入 merged_comps.json（供 DataManager 和 UI 直接使用）

只处理阵容详情相关数据，不涉及趋势/强化符文等无关内容。

用法（CLI）：
    python -m data.merger                   # 合并 cache/raw/ 中的数据
    python -m data.merger --raw ./raw       # 指定原始数据目录
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any, Optional

from config import RAW_DATA_DIR, PROCESSED_DIR, MERGER, get_component_name

logger = logging.getLogger("tft.merger")


class TFTDataMerger:
    """
    将原始 ID 数据合并为 Composition 字典。

    输出格式（merged_comps.json）示例：
    {
      "dark_star_jhin": {
        "slug": "dark_star_jhin",
        "name": "暗星烬",
        "name_en": "Dark Star Jhin",
        "cost": 5,
        "avg_placement": 3.67,
        "win_rate": 0.153,
        "team_code": "...",
        "stats": { ... },
        "units": [ { "id": "TFT17_Jhin", "name": "烬", "cost": 5, ... } ],
        "traits": [ { "id": "...", "name": "暗星", "count": 6 } ],
        "required_components": ["BF大剑", "暴风大剑", ...],
        "unit_stats": [...],
        "emblems": [...],
        "special_items": [...],
        "variants": [...],
        "has_details": true
      }
    }
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

        # 原始实体字典，由 _load_all() 填充
        self._units:      dict = {}
        self._items:      dict = {}
        self._traits:     dict = {}
        self._recipes:    dict = {}   # item_id → [component_id, ...]
        self._comp_cards: list = []

    # ──────────────────────────────────────────────────────────
    # 加载原始数据
    # ──────────────────────────────────────────────────────────

    def _load_json(self, filename: str) -> Optional[Any]:
        path = self.raw_dir / filename
        if not path.exists():
            logger.warning("文件不存在，跳过: %s", path)
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _load_all(self):
        self._units      = self._load_json("entity_units.json")     or {}
        self._items      = self._load_json("entity_items.json")      or {}
        self._traits     = self._load_json("entity_traits.json")     or {}
        self._recipes    = self._load_json("item_recipes.json")      or {}
        self._comp_cards = self._load_json("composition_cards.json") or []

    # ──────────────────────────────────────────────────────────
    # ID → 可读名称的解析助手
    # ──────────────────────────────────────────────────────────

    def _unit_name(self, uid: str) -> str:
        u = self._units.get(uid, {})
        return u.get("name") or u.get("nameCn") or uid

    def _unit_cost(self, uid: str) -> Optional[int]:
        return self._units.get(uid, {}).get("cost")

    def _unit_icon(self, uid: str) -> str:
        """英雄头像路径，格式: /set17/avatar-webp/{id}.webp?v=2"""
        return self._units.get(uid, {}).get("icon", "")

    def _item_name(self, iid: str) -> str:
        # 先查散件名称表（BF大剑等），再查实体装备表
        comp_name = get_component_name(iid, self.lang)
        if comp_name != iid:
            return comp_name
        item = self._items.get(iid, {})
        return item.get("name") or iid

    def _item_icon(self, iid: str) -> str:
        """装备图标路径，格式: /set17/item-webp/{id}.webp"""
        return self._items.get(iid, {}).get("icon", "")

    def _trait_name(self, tid: str) -> str:
        t = self._traits.get(tid, {})
        return t.get("name") or tid

    def _get_components(self, item_id: str) -> list[str]:
        """获取完整装备的散件名称列表（通常 2 个）。"""
        return [self._item_name(c) for c in self._recipes.get(item_id, [])]

    # ──────────────────────────────────────────────────────────
    # 单个阵容合并
    # ──────────────────────────────────────────────────────────

    def _merge_comp(self, slug: str, card: dict) -> dict:
        """
        合并单个阵容数据。
        若没有详情文件，返回仅含卡片信息的简化结构。
        """
        comp_path = self.raw_dir / "compositions" / f"{slug}.json"

        # ── 无详情时的简化版本 ──────────────────────────────────
        if not comp_path.exists():
            return {
                "slug":                slug,
                "name":                card.get("display_name_cn", slug),
                "name_en":             card.get("display_name_en", slug),
                "cost":                card.get("compCost"),
                "avg_placement":       round(card.get("averagePlacementValue", 0.0), 2),
                "win_rate":            round(card.get("winRate", 0.0), 4),
                "team_code":           "",
                "stats":               {},
                "units":               [],
                "traits":              [],
                "required_components": [],
                "unit_stats":          [],
                "emblems":             [],
                "special_items":       [],
                "variants":            [],
                "has_details":         False,
            }

        raw     = json.loads(comp_path.read_text(encoding="utf-8"))
        comp    = raw.get("composition", {})
        details = raw.get("details") or {}
        overview = comp.get("overview", {})
        stats    = overview.get("stats", {})

        # ── 详情统计（保留原始 metrics，同时补齐可读名称/图标）────
        unit_stats = self._parse_unit_stats(details.get("unitStats") or [])
        unit_stats_by_id = {s["id"]: s for s in unit_stats if s.get("id")}

        # ── 核心英雄 ──────────────────────────────────────────
        units = self._parse_units(overview.get("coreUnits", []))

        # ── 英雄装备优先级 ────────────────────────────────────
        priority_map = self._parse_priority(details.get("prioritySections") or [])
        for u in units:
            u["item_priority"] = priority_map.get(u["id"], [])
            u["stats"] = unit_stats_by_id.get(u["id"], {})

        # ── 羁绊 ──────────────────────────────────────────────
        traits = [
            {
                "id":    t.get("id", ""),
                "name":  self._trait_name(t.get("id", "")) or t.get("name", ""),
                "count": t.get("count"),
            }
            for t in overview.get("traits", [])
        ]

        # ── 汇总散件需求（按出现频率倒序）────────────────────
        required_components = self._aggregate_components(units)

        # ── 变体阵容 ──────────────────────────────────────────
        limit    = MERGER["variants_limit"]
        variants = self._parse_variants(comp.get("variants", [])[:limit])

        # ── 转职 / 神器 / 光明装等高价值进阶信息 ────────────────
        emblems       = self._parse_emblems(details.get("emblems") or {})
        special_items = self._parse_special_items(details.get("specialSections") or [])

        # ── 统计数值（优先使用详情页数据）───────────────────
        avg_placement = float(
            stats.get("avgPlacementValue") or card.get("averagePlacementValue") or 0.0
        )
        win_rate = float(
            stats.get("winRateValue") or card.get("winRate") or 0.0
        )

        return {
            "slug":                slug,
            "name":                card.get("display_name_cn", slug),
            "name_en":             card.get("display_name_en", slug),
            "cost":                card.get("compCost"),
            "avg_placement":       round(avg_placement, 2),
            "win_rate":            round(win_rate, 4),
            "team_code":           overview.get("teamCode", ""),
            "stats":               stats,
            "units":               units,
            "traits":              traits,
            "required_components": required_components,
            "unit_stats":          unit_stats,
            "emblems":             emblems,
            "special_items":       special_items,
            "variants":            variants,
            "has_details":         bool(details),
        }

    def _parse_units(self, core_units: list) -> list[dict]:
        """解析 coreUnits 列表，填充装备方案和散件需求。"""
        units = []
        for cu in core_units:
            uid    = cu["id"]
            builds = []
            for build in cu.get("builds", []):
                items_in_build    = []
                components_needed = []
                for slot in build.get("items", []):
                    iid  = slot.get("id", "")
                    items_in_build.append(self._item_record(iid))
                    components_needed.extend(self._get_components(iid))
                builds.append({
                    "index":      build.get("index", len(builds) + 1),
                    "items":      items_in_build,
                    "components": list(dict.fromkeys(components_needed)),
                })

            units.append({
                "id":            uid,
                "name":          self._unit_name(uid) or cu.get("nameCn", uid),
                "cost":          cu.get("cost") or self._unit_cost(uid),
                "icon":          self._unit_icon(uid),
                "builds":        builds,
                "item_priority": [],
                "stats":         {},
            })
        return units

    def _parse_priority(self, priority_sections: list) -> dict[str, list]:
        """
        解析 prioritySections，返回 unit_id → 优先级列表 的映射。
        每个条目包含 id / name / necessity / rating。
        """
        limit      = MERGER["item_priority_limit"]
        result: dict[str, list] = {}
        for ps in priority_sections:
            uid    = ps.get("unitId")
            matrix = ps.get("baseline", {}).get("matrix", {})
            items  = []
            for item_info in matrix.get("items", [])[:limit]:
                iid = item_info.get("itemId", "")
                items.append({
                    "id":        iid,
                    "name":      self._item_name(iid),
                    "icon":      self._item_icon(iid),
                    "category":  self._item_category(iid),
                    "necessity": round(item_info.get("necessity", 0.0), 3),
                    "rating":    item_info.get("rating", ""),
                    "count":     item_info.get("count") or 0,
                    "appearance_rate": round(item_info.get("appearanceRate", 0.0), 4),
                })
            result[uid] = items
        return result

    def _aggregate_components(self, units: list[dict]) -> list[str]:
        """统计所有出装方案中散件出现次数，返回按频率倒序的散件名称列表。"""
        counter: dict[str, int] = {}
        for u in units:
            for build in u.get("builds", []):
                for comp in build.get("components", []):
                    counter[comp] = counter.get(comp, 0) + 1
        return sorted(counter, key=lambda x: -counter[x])

    def _parse_variants(self, variants_raw: list) -> list[dict]:
        """解析变体阵容列表。"""
        result = []
        for v in variants_raw:
            vunits = [self._unit_record(vu.get("id", "")) for vu in v.get("units", [])]
            vtraits = [
                {
                    "id":    vt.get("id", ""),
                    "name":  self._trait_name(vt.get("id", "")),
                    "count": vt.get("count") or vt.get("units_required"),
                }
                for vt in v.get("traits", [])
            ]
            result.append({
                "units":     vunits,
                "traits":    vtraits,
                "stats":     v.get("clustered_stats") or v.get("stats", {}),
                "label":     v.get("variant_label", ""),
                "team_code": v.get("team_code", ""),
            })
        return result

    def _unit_record(self, uid: str) -> dict:
        """返回 UI 可直接消费的英雄摘要。"""
        return {
            "id":   uid,
            "name": self._unit_name(uid),
            "cost": self._unit_cost(uid),
            "icon": self._unit_icon(uid),
        }

    def _item_category(self, iid: str) -> str:
        return self._items.get(iid, {}).get("category", "")

    def _item_record(self, iid: str) -> dict:
        """返回 UI 可直接消费的装备摘要。"""
        return {
            "id":         iid,
            "name":       self._item_name(iid),
            "icon":       self._item_icon(iid),
            "category":   self._item_category(iid),
            "components": self._get_components(iid),
        }

    def _parse_unit_stats(self, rows: list) -> list[dict]:
        """保留单位统计 metrics，并补齐本地化名称/图标。"""
        result = []
        for row in rows:
            uid = row.get("id", "")
            result.append({
                **self._unit_record(uid),
                "metrics": row.get("metrics", []),
            })
        return result

    def _parse_emblems(self, raw: dict) -> list[dict]:
        """解析转职推荐，包括推荐携带者及平均名次。"""
        rows = raw.get("rows", []) if isinstance(raw, dict) else []
        result = []
        for row in rows:
            iid = row.get("itemId", "")
            carriers = []
            for carrier in row.get("carriers", []) or []:
                uid = carrier.get("unit_id", "")
                carriers.append({
                    **self._unit_record(uid),
                    "share": round(carrier.get("share") or 0.0, 4),
                    "count": carrier.get("count"),
                    "best": bool(carrier.get("best")),
                })
            result.append({
                **self._item_record(iid),
                "metrics": row.get("metrics", []),
                "avg_placement": round(row.get("avgPlacement") or 0.0, 2),
                "appearance_rate": round(row.get("appearanceRate") or 0.0, 4),
                "carriers": carriers,
            })
        return result

    def _parse_special_items(self, sections: list) -> list[dict]:
        """解析神器/光明装等特殊装备推荐，保留 bestBuild。"""
        result = []
        for section_idx, section in enumerate(sections, 1):
            section_title = section.get("title") or ""
            for row in section.get("rows", []) or []:
                iid = row.get("itemId", "")
                carrier_id = row.get("carrierId", "")
                best_build = row.get("bestBuild") or {}
                best_items = [
                    self._item_record(item.get("item_id", ""))
                    for item in best_build.get("items", []) or []
                ]
                result.append({
                    **self._item_record(iid),
                    "section_index": section_idx,
                    "section_title": section_title,
                    "metrics": row.get("metrics", []),
                    "carrier": self._unit_record(carrier_id),
                    "best_build": {
                        "items": best_items,
                        "avg_placement": round(best_build.get("avg_placement") or 0.0, 2),
                    } if best_build else {},
                })
        return result

    # ──────────────────────────────────────────────────────────
    # 执行合并
    # ──────────────────────────────────────────────────────────

    def merge(self, output_filename: Optional[str] = None) -> dict[str, dict]:
        """
        执行完整合并流程，返回 {slug: comp_dict} 字典，
        同时写入 processed/merged_comps.json。
        """
        logger.info("开始合并数据 …")
        self._load_all()

        if not self._comp_cards:
            logger.error("没有阵容卡片数据，请先运行爬虫")
            return {}

        # 按平均名次升序排列（名次越低越强）
        sorted_cards = sorted(
            self._comp_cards,
            key=lambda c: c.get("averagePlacementValue", 9.0),
        )

        merged: dict[str, dict] = {}
        for card in sorted_cards:
            slug = card.get("slug")
            if not slug:
                continue
            logger.info("  合并: %s", card.get("display_name_cn", slug))
            merged[slug] = self._merge_comp(slug, card)

        # 写出
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        fname   = output_filename or MERGER["output_filename"]
        outpath = self.processed_dir / fname
        outpath.write_text(
            json.dumps(merged, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("合并完成！共 %d 个阵容 → %s", len(merged), outpath)
        return merged


# ─────────────────────────────────────────────────────────────
# CLI 入口
# ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="TFT Assistant — 数据合并器")
    parser.add_argument("--raw",  default=None, help="原始数据目录（默认: data/cache/raw）")
    parser.add_argument("--out",  default=None, help="输出目录（默认: data/cache/processed）")
    parser.add_argument("--lang", default="zh", help="语言（默认: zh）")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

    raw_dir       = Path(args.raw)  if args.raw  else RAW_DATA_DIR
    processed_dir = Path(args.out)  if args.out  else PROCESSED_DIR

    merger = TFTDataMerger(raw_dir=raw_dir, processed_dir=processed_dir, lang=args.lang)
    merger.merge()


if __name__ == "__main__":
    main()
