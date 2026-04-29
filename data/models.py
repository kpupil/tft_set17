"""
TFT Assistant — 数据模型
========================
用 dataclass 定义所有核心数据结构，确保类型安全、IDE 友好，
同时提供 from_dict / to_dict 序列化支持，方便 JSON 存取。
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional


# ─────────────────────────────────────────────────────────────
# 基础实体
# ─────────────────────────────────────────────────────────────

@dataclass
class ItemComponent:
    """散件（基础合成材料）"""
    id:   str
    name: str

    @staticmethod
    def from_dict(d: dict) -> "ItemComponent":
        return ItemComponent(id=d.get("id", ""), name=d.get("name", ""))

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Item:
    """完整装备（由两个散件合成）"""
    id:         str
    name:       str
    icon:       str       = ""                            # 图标路径（相对 tftable.cc 根目录）
    category:   str       = ""                            # normal / emblem / artifact / radiant …
    components: list[str] = field(default_factory=list)   # 散件名称列表，长度通常为 2

    @staticmethod
    def from_dict(d: dict) -> "Item":
        return Item(
            id=d.get("id", ""),
            name=d.get("name", ""),
            icon=d.get("icon", ""),
            category=d.get("category", ""),
            components=d.get("components", []),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ItemPriority:
    """英雄装备优先级条目（来自 prioritySections）"""
    id:        str
    name:      str
    icon:      str   = ""
    category:  str   = ""
    necessity: float = 0.0  # 0.0–1.0，越高越核心
    rating:    str   = ""   # "Core" / "Recommended" / "Flex" …
    count:     int   = 0
    appearance_rate: float = 0.0

    @staticmethod
    def from_dict(d: dict) -> "ItemPriority":
        return ItemPriority(
            id=d.get("id", ""),
            name=d.get("name", ""),
            icon=d.get("icon", ""),
            category=d.get("category", ""),
            necessity=d.get("necessity", 0.0),
            rating=d.get("rating", ""),
            count=d.get("count", 0),
            appearance_rate=d.get("appearance_rate", 0.0),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Build:
    """英雄的一套出装方案"""
    index:      int         = 1
    items:      list[Item]  = field(default_factory=list)   # 推荐装备
    components: list[str]   = field(default_factory=list)   # 所需散件（去重保序）

    @staticmethod
    def from_dict(d: dict) -> "Build":
        return Build(
            index=d.get("index", 1),
            items=[Item.from_dict(i) for i in d.get("items", [])],
            components=d.get("components", []),
        )

    def to_dict(self) -> dict:
        return {
            "index":      self.index,
            "items":      [i.to_dict() for i in self.items],
            "components": self.components,
        }


@dataclass
class Unit:
    """英雄（棋子）"""
    id:            str
    name:          str
    cost:          Optional[int]      = None
    icon:          str                = ""    # 头像路径（相对 tftable.cc 根目录）
    builds:        list[Build]        = field(default_factory=list)
    item_priority: list[ItemPriority] = field(default_factory=list)
    stats:         dict               = field(default_factory=dict)

    @staticmethod
    def from_dict(d: dict) -> "Unit":
        return Unit(
            id=d.get("id", ""),
            name=d.get("name", ""),
            cost=d.get("cost"),
            icon=d.get("icon", ""),
            builds=[Build.from_dict(b) for b in d.get("builds", [])],
            item_priority=[ItemPriority.from_dict(p) for p in d.get("item_priority", [])],
            stats=d.get("stats", {}),
        )

    def to_dict(self) -> dict:
        return {
            "id":            self.id,
            "name":          self.name,
            "cost":          self.cost,
            "icon":          self.icon,
            "builds":        [b.to_dict() for b in self.builds],
            "item_priority": [p.to_dict() for p in self.item_priority],
            "stats":         self.stats,
        }


@dataclass
class Trait:
    """羁绊"""
    id:    str
    name:  str
    count: Optional[int] = None   # 激活数量

    @staticmethod
    def from_dict(d: dict) -> "Trait":
        return Trait(
            id=d.get("id", ""),
            name=d.get("name", ""),
            count=d.get("count"),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Variant:
    """阵容变体（同一阵容的不同搭配）"""
    units:  list[Unit]    = field(default_factory=list)
    traits: list[Trait]   = field(default_factory=list)
    stats:  dict          = field(default_factory=dict)   # 包含 avgPlacement / winRate 等原始数值
    label:  str           = ""
    team_code: str        = ""

    @staticmethod
    def from_dict(d: dict) -> "Variant":
        return Variant(
            units=[Unit.from_dict(u) for u in d.get("units", [])],
            traits=[Trait.from_dict(t) for t in d.get("traits", [])],
            stats=d.get("stats", {}),
            label=d.get("label", ""),
            team_code=d.get("team_code", ""),
        )

    def to_dict(self) -> dict:
        return {
            "units":  [u.to_dict() for u in self.units],
            "traits": [t.to_dict() for t in self.traits],
            "stats":  self.stats,
            "label":  self.label,
            "team_code": self.team_code,
        }


# ─────────────────────────────────────────────────────────────
# 核心：阵容
# ─────────────────────────────────────────────────────────────

@dataclass
class Composition:
    """
    完整阵容数据（merged_comps.json 中每个 slug 对应的条目）。
    是 UI 和 Bot 模块的主要消费对象。
    """
    slug:                str
    name:                str
    name_en:             str           = ""
    cost:                Optional[int] = None   # 阵容费用评级（1-5）
    avg_placement:       float         = 0.0    # 平均名次（越低越强）
    win_rate:            float         = 0.0    # 胜率（0.0–1.0）
    units:               list[Unit]    = field(default_factory=list)
    traits:              list[Trait]   = field(default_factory=list)
    required_components: list[str]     = field(default_factory=list)  # 散件优先级
    variants:            list[Variant] = field(default_factory=list)
    has_details:         bool          = False
    team_code:           str           = ""
    stats:               dict          = field(default_factory=dict)  # 详情页原始统计
    unit_stats:          list[dict]    = field(default_factory=list)
    emblems:             list[dict]    = field(default_factory=list)
    special_items:       list[dict]    = field(default_factory=list)

    # ── 工厂方法 ──────────────────────────────────────────────

    @staticmethod
    def from_dict(d: dict) -> "Composition":
        return Composition(
            slug=d.get("slug", ""),
            name=d.get("name", ""),
            name_en=d.get("name_en", ""),
            cost=d.get("cost"),
            avg_placement=d.get("avg_placement", 0.0),
            win_rate=d.get("win_rate", 0.0),
            units=[Unit.from_dict(u) for u in d.get("units", [])],
            traits=[Trait.from_dict(t) for t in d.get("traits", [])],
            required_components=d.get("required_components", []),
            variants=[Variant.from_dict(v) for v in d.get("variants", [])],
            has_details=d.get("has_details", False),
            team_code=d.get("team_code", ""),
            stats=d.get("stats", {}),
            unit_stats=d.get("unit_stats", []),
            emblems=d.get("emblems", []),
            special_items=d.get("special_items", []),
        )

    def to_dict(self) -> dict:
        return {
            "slug":                self.slug,
            "name":                self.name,
            "name_en":             self.name_en,
            "cost":                self.cost,
            "avg_placement":       self.avg_placement,
            "win_rate":            self.win_rate,
            "units":               [u.to_dict() for u in self.units],
            "traits":              [t.to_dict() for t in self.traits],
            "required_components": self.required_components,
            "variants":            [v.to_dict() for v in self.variants],
            "has_details":         self.has_details,
            "team_code":           self.team_code,
            "stats":               self.stats,
            "unit_stats":          self.unit_stats,
            "emblems":             self.emblems,
            "special_items":       self.special_items,
        }

    # ── 便捷属性 ──────────────────────────────────────────────

    @property
    def win_rate_pct(self) -> str:
        """胜率百分比字符串，如 '15.2%'"""
        return f"{self.win_rate * 100:.1f}%"

    @property
    def placement_str(self) -> str:
        """平均名次字符串，如 '3.70'"""
        return f"{self.avg_placement:.2f}"

    @property
    def core_units(self) -> list[Unit]:
        """费用 4-5 的核心英雄（通常是 carry）"""
        return [u for u in self.units if u.cost and u.cost >= 4]

    def get_unit(self, unit_id: str) -> Optional[Unit]:
        """通过 ID 查找英雄"""
        for u in self.units:
            if u.id == unit_id:
                return u
        return None


# ─────────────────────────────────────────────────────────────
# 原始实体（爬虫抓取，供 merger 使用）
# ─────────────────────────────────────────────────────────────

@dataclass
class EntityUnit:
    """原始英雄实体（来自 entity_units.json）"""
    id:      str
    name:    str
    cost:    Optional[int] = None
    traits:  list[str]     = field(default_factory=list)   # trait ID 列表
    raw:     dict          = field(default_factory=dict)   # 完整原始数据

    @staticmethod
    def from_raw(uid: str, d: dict) -> "EntityUnit":
        return EntityUnit(
            id=uid,
            name=d.get("name") or d.get("nameCn") or uid,
            cost=d.get("cost"),
            traits=d.get("traits", []),
            raw=d,
        )


@dataclass
class EntityItem:
    """原始装备实体（来自 entity_items.json）"""
    id:   str
    name: str
    raw:  dict = field(default_factory=dict)

    @staticmethod
    def from_raw(iid: str, d: dict) -> "EntityItem":
        return EntityItem(
            id=iid,
            name=d.get("name") or iid,
            raw=d,
        )


@dataclass
class EntityTrait:
    """原始羁绊实体（来自 entity_traits.json）"""
    id:   str
    name: str
    raw:  dict = field(default_factory=dict)

    @staticmethod
    def from_raw(tid: str, d: dict) -> "EntityTrait":
        return EntityTrait(
            id=tid,
            name=d.get("name") or tid,
            raw=d,
        )


@dataclass
class EntityAugment:
    """强化符文实体（来自 entity_augments.json）"""
    id:   str
    name: str
    tier: Optional[int] = None   # 1 / 2 / 3 = 银/金/棱镜
    raw:  dict          = field(default_factory=dict)

    @staticmethod
    def from_raw(aid: str, d: dict) -> "EntityAugment":
        return EntityAugment(
            id=aid,
            name=d.get("name") or aid,
            tier=d.get("tier"),
            raw=d,
        )
