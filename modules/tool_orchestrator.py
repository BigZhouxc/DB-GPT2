# -*- coding: utf-8 -*-
"""工具编排器 —— 数据分析助手的前置智能选择工具。

在 DB-GPT react-agent 执行之前，完成两个前置步骤：
  1. 数据源选择工具：从 App 绑定的多个数据源中选最合适的
  2. 数据表选择工具：从选中库的表结构中选相关表和字段

设计要点（鲁棒性）：
  - 每步独立 try/except，失败不阻断后续流程
  - LLM 返回非 JSON 时有兜底解析
  - 数据源/schema 获取失败时跳过选择，直接透传给 DB-GPT
  - 所有外部调用有超时控制
"""
import json
import logging
import os
import re
from typing import Optional

import httpx

logger = logging.getLogger("tool_orchestrator")

DBGPT_API_BASE = os.getenv("DBGPT_API_BASE", "http://127.0.0.1:5670/api/v2")
# LLM 调用走 DB-GPT chat/completions（OpenAI 兼容接口，v2 返回 JSON）
_LLM_CHAT_URL = DBGPT_API_BASE.rstrip("/") + "/chat/completions"
# Schema 查询走 qna_agent 自身（容器内 localhost）
_SELF_BASE = "http://127.0.0.1:8080"

# SSE 工具事件类型
TOOL_DS_SELECT = "datasource_select"
TOOL_TABLE_SELECT = "table_select"


def make_tool_sse(event_type: str, tool_type: str, data: dict) -> str:
    """构造工具执行 SSE 事件。

    Args:
        event_type: step.start / step.meta / step.done / error
        tool_type: datasource_select / table_select
        data: 事件载荷
    Returns:
        SSE 格式字符串
    """
    payload = {"type": event_type, "tool_type": tool_type, **data}
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


class ToolOrchestrator:
    """数据分析助手前置工具编排器。

    用法：
        orch = ToolOrchestrator(model="TS/GLM-5.2")
        ds_result = await orch.select_datasource("分析销量趋势", ["db1", "db2"])
        tbl_result = await orch.select_tables("分析销量趋势", "db1")
    """

    def __init__(self, model: str = "TS-MOMA/DeepSeek-V4-Flash"):
        self.model = model
        self._timeout = 60  # 单次 LLM 调用超时

    # ------------------------------------------------------------------
    # 工具 1：数据源选择
    # ------------------------------------------------------------------
    async def select_datasource(
        self, question: str, db_names: list[str]
    ) -> dict:
        """从多个候选数据源中选择最合适的一个。

        Args:
            question: 用户自然语言问题
            db_names: 候选数据源名称列表

        Returns:
            {"datasource": str, "reason": str} 或 {"datasource": db_names[0], "reason": "默认选择", "fallback": True}
        """
        if not db_names:
            return {"datasource": "", "reason": "无可用数据源", "fallback": True}

        if len(db_names) == 1:
            return {
                "datasource": db_names[0],
                "reason": "仅有一个数据源，直接使用",
                "fallback": True,
            }

        # 收集数据源摘要
        ds_summaries = await self._collect_ds_summaries(db_names)

        prompt = self._build_ds_prompt(question, ds_summaries)

        try:
            content = await self._call_llm(prompt)
            result = self._parse_json_response(content)
            ds = result.get("datasource", "").strip()

            # 校验返回的数据源在候选列表中
            if ds and ds in db_names:
                return {
                    "datasource": ds,
                    "reason": result.get("reason", ""),
                }
            else:
                # LLM 返回了不在列表中的数据源，尝试模糊匹配
                for name in db_names:
                    if ds and ds.lower() in name.lower():
                        return {
                            "datasource": name,
                            "reason": f"模糊匹配: {result.get('reason', '')}",
                        }
                # 兜底：取第一个
                logger.warning(
                    "数据源选择 LLM 返回值 %r 不在候选列表 %r 中，使用兜底",
                    ds,
                    db_names,
                )
                return {
                    "datasource": db_names[0],
                    "reason": f"LLM 返回值不在候选列表中，默认选择。原始返回: {ds}",
                    "fallback": True,
                }
        except Exception as e:
            logger.warning("数据源选择失败: %s，使用兜底", e)
            return {
                "datasource": db_names[0],
                "reason": f"选择工具异常，默认使用第一个数据源: {e}",
                "fallback": True,
            }

    # ------------------------------------------------------------------
    # 工具 2：数据表选择
    # ------------------------------------------------------------------
    async def select_tables(
        self, question: str, datasource_name: str
    ) -> dict:
        """从选中数据源的表结构中选择相关表和字段。

        Args:
            question: 用户自然语言问题
            datasource_name: 已选中的数据源名称

        Returns:
            {"tables": ["t1","t2"], "fields": {"t1": ["col1","col2"]}, "reason": "..."}
            失败时返回空列表（不阻断后续 SQL 生成）
        """
        if not datasource_name:
            return {"tables": [], "fields": {}, "reason": "无数据源", "fallback": True}

        # 获取数据源的表结构
        schema = await self._get_schema(datasource_name)
        if not schema or not schema.get("tables"):
            return {
                "tables": [],
                "fields": {},
                "reason": f"获取 {datasource_name} 表结构失败",
                "fallback": True,
            }

        prompt = self._build_table_prompt(question, datasource_name, schema)

        try:
            content = await self._call_llm(prompt)
            result = self._parse_json_response(content)
            tables = result.get("tables", [])
            fields = result.get("fields", {})

            # 校验返回的表名在 schema 中存在
            valid_tables = [t for t in tables if isinstance(t, str) and t]
            schema_tables = {t["table_name"] for t in schema.get("tables", [])}
            validated_tables = []
            validated_fields = {}

            for t in valid_tables:
                if t in schema_tables:
                    validated_tables.append(t)
                    # 校验字段名也在 schema 中
                    tbl_cols = {
                        c["name"] for st in schema["tables"] if st["table_name"] == t for c in st["columns"]
                    }
                    raw_fields = fields.get(t, [])
                    if isinstance(raw_fields, list):
                        validated_fields[t] = [
                            f for f in raw_fields if isinstance(f, str) and f in tbl_cols
                        ]

            if not validated_tables:
                # LLM 返回的表名都不在 schema 中，兜底返回全部表名
                all_table_names = [t["table_name"] for t in schema.get("tables", [])]
                logger.warning(
                    "数据表选择 LLM 返回表名 %r 不在 schema 中，使用全部表",
                    tables,
                )
                return {
                    "tables": all_table_names,
                    "fields": {},
                    "reason": "LLM 返回表名无效，使用全部表",
                    "fallback": True,
                }

            return {
                "tables": validated_tables,
                "fields": validated_fields,
                "reason": result.get("reason", ""),
            }
        except Exception as e:
            logger.warning("数据表选择失败: %s，跳过表过滤", e)
            all_table_names = [t["table_name"] for t in schema.get("tables", [])]
            return {
                "tables": all_table_names,
                "fields": {},
                "reason": f"选择工具异常，使用全部表: {e}",
                "fallback": True,
            }

    # ------------------------------------------------------------------
    # LLM 调用（通过 DB-GPT chat/completions，OpenAI 兼容接口）
    # ------------------------------------------------------------------
    async def _call_llm(self, prompt: str) -> str:
        """调用 LLM 生成文本。

        通过 DB-GPT /api/v2/chat/completions 调用（OpenAI 兼容），
        消息角色用标准的 user/assistant，返回 JSON 格式。

        Returns:
            LLM 生成的文本内容
        """
        body = {
            "messages": [{"role": "user", "content": prompt}],
            "model": self.model,
            "temperature": 0.1,
            "max_tokens": 1024,
        }

        async with httpx.AsyncClient(
            timeout=self._timeout, trust_env=False
        ) as client:
            resp = await client.post(_LLM_CHAT_URL, json=body)
            if resp.status_code != 200:
                raise RuntimeError(
                    f"LLM 调用失败 {resp.status_code}: {resp.text[:200]}"
                )
            data = resp.json()
            # OpenAI 兼容格式：choices[0].message.content
            content = ""
            choices = data.get("choices", [])
            if choices and isinstance(choices, list):
                msg = choices[0].get("message", {})
                content = msg.get("content", "")
            # 兜底：直接取 text 字段
            if not content:
                content = data.get("text", "")
            if not content:
                raise RuntimeError(f"LLM 返回空内容: {json.dumps(data, ensure_ascii=False)[:200]}")
            return content

    # ------------------------------------------------------------------
    # 数据源摘要收集
    # ------------------------------------------------------------------
    async def _collect_ds_summaries(self, db_names: list[str]) -> list[dict]:
        """收集每个数据源的摘要信息（名称 + 类型 + 表数量 + 注释）。"""
        summaries = []
        # 先一次性获取所有数据源列表
        ds_meta = {}
        try:
            async with httpx.AsyncClient(
                timeout=15, trust_env=False
            ) as client:
                resp = await client.get(f"{_SELF_BASE}/datasources")
                if resp.status_code == 200:
                    data = resp.json()
                    for item in data.get("datasources", []):
                        ds_meta[item.get("db_name", "")] = item
        except Exception as e:
            logger.debug("获取数据源列表失败: %s", e)

        for name in db_names:
            meta = ds_meta.get(name, {})
            info = {
                "name": name,
                "type": meta.get("db_type", "unknown"),
                "tables": 0,
                "comment": meta.get("comment", ""),
            }

            # 获取表数量和表名
            try:
                schema = await self._get_schema(name)
                if schema and schema.get("tables"):
                    info["tables"] = len(schema["tables"])
                    # 补充表名列表（截断防止过长）
                    table_names = [t["table_name"] for t in schema["tables"][:20]]
                    info["table_names"] = table_names
            except Exception as e:
                logger.debug("获取数据源 %s schema 失败: %s", name, e)

            summaries.append(info)
        return summaries

    # ------------------------------------------------------------------
    # Schema 获取（通过 qna_agent 自身接口，容器内 localhost）
    # ------------------------------------------------------------------
    async def _get_schema(self, datasource_name: str) -> Optional[dict]:
        """通过 qna_agent 的接口获取 schema。

        流程：先 GET /datasources 找到 name 对应的 ID，
        再 GET /datasources/{id}/schema 获取表结构。

        Returns:
            {"db_name": "...", "db_type": "...", "tables": [...]} 或 None
        """
        try:
            # 1. 获取数据源列表，找到 datasource_name 对应的 ID
            async with httpx.AsyncClient(
                timeout=15, trust_env=False
            ) as client:
                resp = await client.get(f"{_SELF_BASE}/datasources")
                if resp.status_code != 200:
                    logger.warning("获取数据源列表失败: %s", resp.status_code)
                    return None
                data = resp.json()
                items = data.get("datasources", [])
                ds_id = None
                for item in items:
                    if item.get("db_name") == datasource_name:
                        ds_id = item.get("id")
                        break
                if ds_id is None:
                    logger.warning("数据源 %s 不在列表中", datasource_name)
                    return None

            # 2. 用 ID 获取 schema
            async with httpx.AsyncClient(
                timeout=30, trust_env=False
            ) as client:
                resp = await client.get(
                    f"{_SELF_BASE}/datasources/{ds_id}/schema"
                )
                if resp.status_code != 200:
                    logger.warning(
                        "获取 schema 失败: %s %s",
                        resp.status_code,
                        resp.text[:200],
                    )
                    return None
                data = resp.json()
                schema = data.get("schema")
                if schema and schema.get("tables"):
                    return schema
                return None

        except Exception as e:
            logger.warning("获取 schema 失败: %s", e)
            return None

    # ------------------------------------------------------------------
    # Prompt 构建
    # ------------------------------------------------------------------
    def _build_ds_prompt(self, question: str, ds_summaries: list[dict]) -> str:
        """构建数据源选择 prompt。"""
        lines = []
        for ds in ds_summaries:
            table_list = ", ".join(ds.get("table_names", []))
            lines.append(
                f"- 数据源: {ds['name']}\n"
                f"  类型: {ds['type']}, 表数量: {ds['tables']}\n"
                f"  描述: {ds.get('comment', '')}\n"
                f"  包含表: {table_list}"
            )
        ds_text = "\n".join(lines)

        return f"""你是一个数据分析助手的数据源选择工具。
用户问题：{question}

可用的数据源列表：
{ds_text}

请根据用户问题，选择最合适的数据源来回答这个问题。
只返回 JSON 格式（不要包含其他文本）：
{{"datasource": "数据源名称", "reason": "选择理由（一句话）"}}"""

    def _build_table_prompt(
        self, question: str, datasource: str, schema: dict
    ) -> str:
        """构建数据表选择 prompt。"""
        lines = []
        for table in schema.get("tables", []):
            cols = table.get("columns", [])
            col_info = ", ".join(
                f"{c['name']}({c.get('type', '')})"
                + (f"[{c.get('comment', '')}]" if c.get("comment") else "")
                for c in cols[:15]  # 每表最多 15 列，控制 token
            )
            lines.append(
                f"- 表名: {table['table_name']}\n"
                f"  注释: {table.get('table_comment', '')}\n"
                f"  字段: {col_info}"
            )
        table_text = "\n".join(lines)

        return f"""你是一个数据分析助手的数据表选择工具。
用户问题：{question}

数据源 {datasource} 的表结构：
{table_text}

请选择回答该问题需要的数据表和字段。只返回 JSON 格式（不要包含其他文本）：
{{"tables": ["表名1", "表名2"], "fields": {{"表名1": ["字段1", "字段2"]}}, "reason": "选择理由"}}"""

    # ------------------------------------------------------------------
    # JSON 响应解析（鲁棒）
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_json_response(content: str) -> dict:
        """从 LLM 响应中提取 JSON 对象。

        支持多种格式：
        1. 纯 JSON
        2. markdown 代码块包裹的 JSON
        3. 文本中嵌入的 JSON
        """
        if not content:
            return {}

        content = content.strip()

        # 1. 直接 JSON 解析
        try:
            return json.loads(content)
        except (json.JSONDecodeError, ValueError):
            pass

        # 2. markdown 代码块中的 JSON
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except (json.JSONDecodeError, ValueError):
                pass

        # 3. 文本中第一个 JSON 对象
        m2 = re.search(r"\{[^{}]*\}", content, re.DOTALL)
        if m2:
            try:
                return json.loads(m2.group(0))
            except (json.JSONDecodeError, ValueError):
                pass

        # 4. 查找最外层花括号
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(content[start : end + 1])
            except (json.JSONDecodeError, ValueError):
                pass

        logger.warning("无法解析 LLM 响应为 JSON: %s", content[:200])
        return {}
