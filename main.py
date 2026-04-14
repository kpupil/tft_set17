"""
TFT Assistant — 主入口
======================
统筹协调各模块的启动与交互。

当前支持的运行模式：
  python main.py data            # 仅抓取 + 合并数据
  python main.py data --fast     # 快速模式（跳过阵容详情）
  python main.py query <关键词>  # 命令行查询阵容（调试用）
  python main.py ui              # 启动悬浮 UI（待实现）
  python main.py bot             # 启动自动拿牌（待实现）
"""

import argparse
import json
import logging
import sys

from config import ROOT_DIR
from data.manager import DataManager


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


# ─── 子命令：data ─────────────────────────────────────────────

def cmd_data(args):
    """抓取 + 合并数据。"""
    dm = DataManager(lang=args.lang)
    dm.refresh(force=args.fast)
    print(f"\n数据已更新：{dm.summary()}")


# ─── 子命令：query ────────────────────────────────────────────

def cmd_query(args):
    """命令行查询阵容（调试 / 验证数据用）。"""
    dm = DataManager(lang=args.lang)
    if not dm.load():
        print("没有本地数据，请先运行:  python main.py data")
        sys.exit(1)

    keyword = " ".join(args.keyword)
    results = dm.search_comp(keyword) if keyword else dm.get_comps_sorted(top_n=10)

    print(f"\n{'─'*55}")
    print(f"  搜索: '{keyword}' — 找到 {len(results)} 个阵容")
    print(f"{'─'*55}")
    for comp in results:
        trend_icon = {"up": "↑", "down": "↓", "stable": "→"}.get(comp.trending, "→")
        unit_names = " / ".join(u.name for u in comp.units[:5])
        print(
            f"  [{comp.placement_str}名] {trend_icon}  {comp.name:<16} "
            f"胜率{comp.win_rate_pct}  |  {unit_names}"
        )
    print(f"{'─'*55}\n")


# ─── 子命令：ui ───────────────────────────────────────────────

def cmd_ui(_args):
    """启动悬浮 UI。"""
    from ui.overlay import run_overlay
    run_overlay()


# ─── 子命令：bot ──────────────────────────────────────────────

def cmd_bot(_args):
    """启动自动拿牌机器人（待实现）。"""
    print("Bot 模块尚未实现，敬请期待！")


# ─────────────────────────────────────────────────────────────
# CLI 解析
# ─────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tft-assistant",
        description="TFT Assistant — 云顶之弈辅助工具",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="详细日志")
    parser.add_argument("--lang", default="zh", choices=["zh", "en", "ko", "ja", "fr"])

    sub = parser.add_subparsers(dest="command", required=True)

    # data
    p_data = sub.add_parser("data", help="抓取并合并最新数据")
    p_data.add_argument("--fast", action="store_true", help="忽略缓存，强制重新抓取所有详情")
    p_data.set_defaults(func=cmd_data)

    # query
    p_query = sub.add_parser("query", help="命令行查询阵容")
    p_query.add_argument("keyword", nargs="*", help="搜索关键词（留空显示 Top10）")
    p_query.set_defaults(func=cmd_query)

    # ui（占位）
    p_ui = sub.add_parser("ui", help="启动悬浮 UI（开发中）")
    p_ui.set_defaults(func=cmd_ui)

    # bot（占位）
    p_bot = sub.add_parser("bot", help="启动自动拿牌（开发中）")
    p_bot.set_defaults(func=cmd_bot)

    return parser


def main():
    parser = build_parser()
    args   = parser.parse_args()
    setup_logging(args.verbose)
    args.func(args)


if __name__ == "__main__":
    main()
