# -*- coding: utf-8 -*-
"""会话（conv_uid）管理器 —— 线程安全的内存会话池。

每个数据源/业务标识独立会话，避免长会话上下文污染。
"""
import threading
import uuid
from typing import Dict


class SessionManager:
    """线程安全的会话池。"""

    def __init__(self):
        self._pool: Dict[str, str] = {}  # key -> conv_uid
        self._lock = threading.Lock()

    def get_or_create(self, key: str) -> str:
        """获取或创建会话。"""
        with self._lock:
            if key not in self._pool:
                self._pool[key] = str(uuid.uuid4())
            return self._pool[key]

    def new(self, key: str) -> str:
        """强制新建会话。"""
        with self._lock:
            self._pool[key] = str(uuid.uuid4())
            return self._pool[key]

    def set(self, key: str, conv_uid: str):
        """手动指定会话。"""
        with self._lock:
            self._pool[key] = conv_uid

    def reset(self):
        """清空所有会话。"""
        with self._lock:
            self._pool.clear()

    def list(self) -> Dict[str, str]:
        """列出所有会话。"""
        with self._lock:
            return dict(self._pool)

    def remove(self, key: str):
        """移除指定会话。"""
        with self._lock:
            self._pool.pop(key, None)


# 全局单例
sessions = SessionManager()
