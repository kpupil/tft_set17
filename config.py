"""
TFT Assistant — 全局配置
========================
所有模块共享的配置项集中在此，避免硬编码散落各处。

打包场景下将“应用资源目录”和“用户可写数据目录”分离：
  - RESOURCE_ROOT: 程序内置只读资源
  - APP_DATA_ROOT: 用户侧可写缓存 / 配置
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys


def _detect_resource_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def _detect_app_data_root(app_name: str = "TFT Assistant") -> Path:
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / app_name
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / app_name
        return home / "AppData" / "Roaming" / app_name
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / app_name
    return home / ".local" / "share" / app_name


RESOURCE_ROOT = _detect_resource_root()
ROOT_DIR = RESOURCE_ROOT
APP_DATA_ROOT = _detect_app_data_root()

BUNDLED_DATA_DIR = RESOURCE_ROOT / "data" / "cache"
DATA_DIR = APP_DATA_ROOT / "data" / "cache"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
IMAGE_DIR = DATA_DIR / "images"
REGION_CONFIG_PATH = DATA_DIR / "region_config.json"


def _seed_dir(src: Path, dst: Path):
    if not src.exists():
        return
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            _seed_dir(item, target)
        elif not target.exists():
            shutil.copy2(item, target)


def ensure_app_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    # 首次运行时把内置数据拷到用户可写目录，便于桌面应用正常更新缓存。
    _seed_dir(BUNDLED_DATA_DIR / "raw", RAW_DATA_DIR)
    _seed_dir(BUNDLED_DATA_DIR / "processed", PROCESSED_DIR)
    _seed_dir(BUNDLED_DATA_DIR / "images", IMAGE_DIR)


ensure_app_dirs()


# ─── 爬虫配置 ─────────────────────────────────────────────────
SCRAPER = {
    "base_url": "https://tftable.cc",
    "default_lang": "zh",
    "supported_langs": ["zh", "en", "ko", "ja", "fr"],
    "timeout": 30,
    "request_delay": 0.3,
    "max_retries": 3,
    "workers": 30,
    "detail_cache_max_age_hours": 24,
    "headers": {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/html, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://tftable.cc/",
    },
}


# ─── 数据合并配置 ─────────────────────────────────────────────
MERGER = {
    "item_priority_limit": 6,
    "variants_limit": 5,
    "output_filename": "merged_comps.json",
}


# ─── TFT 基础散件名称映射（tftable.cc 不返回散件名，手动维护）──
COMPONENT_NAMES: dict[str, dict[str, str]] = {
    "TFT_Item_BFSword": {"zh": "BF大剑", "en": "B.F. Sword"},
    "TFT_Item_RecurveBow": {"zh": "反曲之弓", "en": "Recurve Bow"},
    "TFT_Item_SparringGloves": {"zh": "拳击手套", "en": "Sparring Gloves"},
    "TFT_Item_NeedlesslyLargeRod": {"zh": "虚空法杖", "en": "Needlessly Large Rod"},
    "TFT_Item_TearOfTheGoddess": {"zh": "女神之泪", "en": "Tear of the Goddess"},
    "TFT_Item_ChainVest": {"zh": "锁子甲", "en": "Chain Vest"},
    "TFT_Item_NegatronCloak": {"zh": "负极斗篷", "en": "Negatron Cloak"},
    "TFT_Item_GiantsBelt": {"zh": "巨人腰带", "en": "Giant's Belt"},
}


def get_component_name(item_id: str, lang: str = "zh") -> str:
    """根据散件 ID 和语言返回可读名称，找不到则返回原 ID。"""
    entry = COMPONENT_NAMES.get(item_id)
    if not entry:
        return item_id
    return entry.get(lang) or entry.get("zh") or item_id


# ─── 悬浮 UI 配置（预留，ui 模块使用）────────────────────────
UI = {
    "window_title": "TFT Assistant",
    "opacity": 0.92,
    "always_on_top": True,
    "default_width": 380,
    "default_height": 600,
    "theme": "dark",
    "hotkey_toggle": "<ctrl>+<shift>+t",      # pynput 格式：切换窗口显隐
    "hotkey_autopick": "<ctrl>+<alt>+a",      # pynput 格式：开关自动拿牌
}


# ─── 自动操作配置（预留，bot 模块使用）───────────────────────
BOT = {
    "enabled": False,
    "confidence": 0.85,
    "pick_delay_ms": 200,
    "scan_interval_ms": 500,
}
