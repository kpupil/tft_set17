"""
TFT Assistant — 全局快捷键管理器
================================
使用 pynput 注册系统级全局热键，不依赖窗口焦点。
pynput 回调在后台线程执行，通过 Qt 信号安全地桥接到主线程。

用法：
    from ui.global_hotkey import GlobalHotkeyManager

    mgr = GlobalHotkeyManager.instance()
    mgr.register("<ctrl>+<shift>+t", some_qt_slot)
    mgr.start()          # 启动监听
    mgr.stop()           # 退出时停止

pynput 热键格式示例：
    "<ctrl>+<shift>+a"
    "<ctrl>+<shift>+t"
"""

from __future__ import annotations

import threading
from typing import Callable

from PyQt6.QtCore import QObject, pyqtSignal

from pynput.keyboard import GlobalHotKeys


class _HotkeyBridge(QObject):
    """
    Qt 信号桥：pynput 后台线程 → Qt 主线程。
    每个热键对应一个唯一的 int id，通过 triggered 信号传递。
    """
    triggered = pyqtSignal(int)


class GlobalHotkeyManager:
    """
    全局快捷键管理器（单例）。

    register(hotkey_str, callback)  — 注册热键与对应的回调
    start()                         — 启动 pynput 监听线程
    stop()                          — 停止监听
    """

    _instance: GlobalHotkeyManager | None = None

    @classmethod
    def instance(cls) -> GlobalHotkeyManager:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._bridge = _HotkeyBridge()
        self._callbacks: dict[int, Callable] = {}
        self._hotkey_map: dict[str, int] = {}   # pynput_str → id
        self._next_id = 0
        self._listener: GlobalHotKeys | None = None
        self._bridge.triggered.connect(self._dispatch)

    # ── 注册 ─────────────────────────────────────────────────────

    def register(self, hotkey_str: str, callback: Callable) -> int:
        """
        注册一个全局热键。

        Parameters
        ----------
        hotkey_str : str
            pynput 格式的热键字符串，例如 "<ctrl>+<shift>+a"
        callback : Callable
            在 **Qt 主线程** 中执行的无参回调。

        Returns
        -------
        int  热键 id（可用于 unregister）
        """
        hid = self._next_id
        self._next_id += 1
        self._hotkey_map[hotkey_str] = hid
        self._callbacks[hid] = callback
        return hid

    def unregister(self, hid: int):
        """按 id 移除热键（需 restart 生效）。"""
        self._callbacks.pop(hid, None)
        self._hotkey_map = {
            k: v for k, v in self._hotkey_map.items() if v != hid
        }

    # ── 生命周期 ──────────────────────────────────────────────────

    def start(self):
        """启动 pynput 全局热键监听（后台守护线程）。"""
        self.stop()

        if not self._hotkey_map:
            return

        bindings: dict[str, Callable] = {}
        for hotkey_str, hid in self._hotkey_map.items():
            # 用默认参数捕获当前 hid 值
            bindings[hotkey_str] = lambda _id=hid: self._bridge.triggered.emit(_id)

        self._listener = GlobalHotKeys(bindings)
        self._listener.daemon = True
        self._listener.start()

    def stop(self):
        """停止监听线程。"""
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def restart(self):
        """重建监听器（注册表变化后调用）。"""
        self.start()

    # ── 内部 ──────────────────────────────────────────────────────

    def _dispatch(self, hid: int):
        """主线程回调分发。"""
        cb = self._callbacks.get(hid)
        if cb:
            cb()
