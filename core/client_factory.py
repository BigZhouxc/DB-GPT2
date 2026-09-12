# -*- coding: utf-8 -*-
"""DB-GPT Client 单例工厂。

通过环境变量配置，全局复用同一个 httpx.AsyncClient，
避免每次请求都创建新连接。
"""
import os
from typing import Optional

import httpx
from dbgpt_client import Client

# 全局单例
_client: Optional[Client] = None


def get_client() -> Client:
    """获取全局 DB-GPT Client 单例。

    配置来源（环境变量）：
        DBGPT_API_BASE  — DB-GPT API 地址，默认 http://127.0.0.1:5670/api/v2
        DBGPT_API_KEY   — API Key（可选）
        TIMEOUT         — 请求超时秒数，默认 300
    """
    global _client
    if _client is None:
        api_base = os.getenv("DBGPT_API_BASE", "http://127.0.0.1:5670/api/v2")
        # 关键：SDK 的 Client.get()/post() 会把 path 拼成 {api_base}/serve{path}，
        # 并不做 /api/v2 补全。必须确保 api_base 以 /api/v2 结尾，否则全部 404。
        if not api_base.endswith("/api/v2"):
            if "/api/v1" in api_base:
                api_base = api_base.replace("/api/v1", "/api/v2")
            elif not api_base.endswith("/api"):
                api_base = api_base.rstrip("/") + "/api/v2"
        api_key = os.getenv("DBGPT_API_KEY", "") or None
        timeout = float(os.getenv("TIMEOUT", "300"))
        _client = Client(api_base=api_base, api_key=api_key, timeout=timeout)

        # 关键：dbgpt_client 内部用 httpx.AsyncClient(trust_env=True)，
        # 会读取宿主机遗留的 HTTP_PROXY 环境变量，导致容器内连不上 DB-GPT。
        # 这里替换为 trust_env=False 的 client，彻底绕过代理。
        old = _client._http_client
        old_headers = old.headers
        old_timeout = old.timeout
        old._transport
        _client._http_client = httpx.AsyncClient(
            headers=old_headers,
            timeout=old_timeout,
            trust_env=False,
        )
        # 关闭旧 client
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(old.aclose())
            else:
                loop.run_until_complete(old.aclose())
        except Exception:
            pass

    return _client
