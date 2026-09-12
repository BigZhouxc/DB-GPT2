# -*- coding: utf-8 -*-
"""QnAAgent —— 基于 DB-GPT SDK (dbgpt_client) 封装的智能问数 Agent 核心。

职责：
  1. 调用 DB-GPT 的 chat_data / chat_react_agent 完成 NL2SQL + 执行 + 回答
  2. 会话（conv_uid）管理：一数据源一会话，可外部传入复用
  3. 响应解析：从 <chart-view> 提取 sql / data / display_type，剥离纯文本回答
  4. 工程兜底：MySQL 双引号方言归一化、反问检测、超时/异常捕获

用法（函数级，可直接在 python/脚本中调用）：
    agent = QnAAgent(api_base="http://127.0.0.1:5670/api/v2", api_key=None,
                     model="TS-MOMA/DeepSeek-V4-Flash")
    result = await agent.ask("列出所有书名", datasource="chase_book")
"""
import html
import json
import re
import uuid
from typing import Optional

from dbgpt_client import Client


class QnAAgent:
    def __init__(
        self,
        api_base: str = "http://127.0.0.1:5670/api/v2",
        api_key: Optional[str] = None,
        model: str = "TS-MOMA/DeepSeek-V4-Flash",
        conv_uid: Optional[str] = None,
        timeout: float = 300,
    ):
        self.client = Client(api_base=api_base, api_key=api_key, timeout=timeout)
        self.model = model
        self.conv_uid = conv_uid or str(uuid.uuid4())

    # ------------------------------------------------------------------
    # 对外主方法：单轮问数
    # ------------------------------------------------------------------
    async def ask(
        self,
        question: str,
        datasource: str,
        chat_mode: str = "chat_data",
        temperature: float = 0.2,
        max_new_tokens: int = 4000,
        normalize_mysql: bool = True,
    ) -> dict:
        """向 DB-GPT 提问，返回结构化结果。

        Args:
            question: 自然语言问题
            datasource: DB-GPT 中已注册的数据源名（chat_param）
            chat_mode: chat_data（单轮快） / chat_react_agent（多轮慢）
            temperature / max_new_tokens: LLM 采样参数
            normalize_mysql: 是否做 MySQL 双引号方言归一化
                （sqlite 数据源时双引号合法，请传 False）

        Returns:
            {
                "ok": bool,              # 调用是否成功（网络/服务层面）
                "answer": str,           # 模型自然语言回答（已剥离 chart-view）
                "sql": str,              # 模型生成并执行的 SQL
                "data": list|None,       # 执行结果（list[dict]）
                "display_type": str,     # 展示类型 response_table 等
                "asked": bool,           # True=模型反问/未给出数据
                "conv_uid": str,         # 本次使用的会话
                "error": str,            # ok=False 时错误信息
            }
        """
        try:
            resp = await self.client.chat(
                model=self.model,
                messages=question,
                chat_mode=chat_mode,
                chat_param=datasource,
                conv_uid=self.conv_uid,
                temperature=temperature,
                max_new_tokens=max_new_tokens,
            )
        except Exception as e:
            return self._err(f"调用 DB-GPT 异常: {e}")

        # 非 200 时 client.chat 直接返回 dict（含 error 字段）
        if isinstance(resp, dict):
            return self._err(f"DB-GPT 返回非 200: {resp}")

        try:
            content = resp.choices[0].message.content or ""
        except Exception as e:
            return self._err(f"响应解析异常: {e}")

        chart = self._parse_chart_view(content)
        sql = (chart or {}).get("sql", "")
        # MySQL 双引号方言归一化：SELECT "列名" -> SELECT `列名`；字符串值保留单引号
        if normalize_mysql and chart and sql:
            sql = self.normalize_mysql_sql(sql)
        return {
            "ok": True,
            "answer": self._extract_plain(content),
            "sql": sql,
            "data": (chart or {}).get("data"),
            "display_type": (chart or {}).get("display_type", "response_table"),
            "asked": chart is None,
            "conv_uid": self.conv_uid,
            "error": "",
        }

    # ------------------------------------------------------------------
    # 流式问数（逐 token 输出）
    # ------------------------------------------------------------------
    async def ask_stream(self, question: str, datasource: str,
                         chat_mode: str = "chat_data"):
        """流式版本：逐个产出文本片段。"""
        async for chunk in self.client.chat_stream(
            model=self.model,
            messages=question,
            chat_mode=chat_mode,
            chat_param=datasource,
            conv_uid=self.conv_uid,
            temperature=0.2,
            max_new_tokens=4000,
        ):
            try:
                delta = chunk.choices[0].delta.content
            except Exception:
                delta = None
            if delta:
                yield delta

    # ------------------------------------------------------------------
    # 会话管理
    # ------------------------------------------------------------------
    def new_session(self) -> str:
        """新建会话（建议每个数据源/每轮评测独立会话，避免上下文污染）。"""
        self.conv_uid = str(uuid.uuid4())
        return self.conv_uid

    def set_session(self, conv_uid: str):
        self.conv_uid = conv_uid
        return self

    # ------------------------------------------------------------------
    # 响应解析（与评测脚本同源）
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_chart_view(content: str):
        if not content:
            return None
        m = re.search(r"<chart-view\s+content=[\"'](.*?)[\"']\s*/>", content, re.S)
        if not m:
            return None
        raw = html.unescape(m.group(1))
        try:
            return json.loads(raw)
        except Exception:
            return None

    @staticmethod
    def _extract_plain(content: str) -> str:
        text = re.sub(r"<chart-view.*?/>", "", content, flags=re.S)
        text = re.sub(r"<[^>]+>", "", text)
        return text.strip()

    @staticmethod
    def normalize_mysql_sql(sql: str) -> str:
        """MySQL 方言归一化（两步，避免误伤字符串值）。

        背景：模型对 MySQL 常生成 `SELECT "剧名" FROM "电视剧"`，而 MySQL 默认把
        双引号当字符串字面量，导致整列返回字面量或 1064 语法错误。
        处理：
          1) 等号/IN/括号后的 `"值"` 是字符串值 -> 转成单引号 `'值'`
          2) 其余 `"标识符"`（列名/表名）-> 转成反引号 `` `标识符` ``

        示例：
          SELECT "剧名" FROM "电视剧" WHERE 名称 = "东方卫视"
          -> SELECT `剧名` FROM `电视剧` WHERE 名称 = '东方卫视'
        """
        # 1) 值上下文（= / ( / , 后的双引号字符串）-> 单引号
        sql = re.sub(r'([=(,]\s*)"([^"]*)"', r"\1'\2'", sql)
        # 2) 标识符上下文 -> 反引号
        sql = re.sub(r'"([\w\u4e00-\u9fa5]+)"', r"`\1`", sql)
        return sql

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    @staticmethod
    def _new_uid() -> str:
        return str(uuid.uuid4())

    @staticmethod
    def _err(msg: str) -> dict:
        return {"ok": False, "answer": "", "sql": "", "data": None,
                "display_type": "", "asked": False,
                "conv_uid": "", "error": msg}
