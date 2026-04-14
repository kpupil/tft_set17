"""
TFT Assistant — 桌面应用入口
============================
供 PyInstaller 打包使用，直接启动悬浮 UI。
"""

from __future__ import annotations

import logging

from main import setup_logging
from ui.overlay import run_overlay


def main():
    setup_logging(verbose=False)
    logging.getLogger("tft.app").info("启动桌面应用")
    run_overlay()


if __name__ == "__main__":
    main()
