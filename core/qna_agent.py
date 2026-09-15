# -*- coding: utf-8 -*-
"""核心问答 Agent —— 基于 DB-GPT SDK 封装。

职责：
  1. 调用 DB-GPT chat API 完成 NL2SQL + 执行 + 回答（chat_data / chat_knowledge / chat_flow）
  2. 响应解析：从 <chart-view> 提取 sql / data / display_type，剥离纯文本回答
  3. 工程兜底：MySQL 双引号方言归一化、反问检测、超时/异常捕获
"""
import html
import json
import re
import uuid
from enum import Enum
from typing import AsyncGenerator, Optional

from dbgpt_client import Client


class ChatMode(str, Enum):
    """DB-GPT 支持的问答模式。"""

    NORMAL = "chat_normal"          # 普通对话
    DATA = "chat_data"              # 数据对话（NL2SQL）
    KNOWLEDGE = "chat_knowledge"    # 知识库问答
    FLOW = "chat_flow"             # AWEL Flow 问答
    APP = "chat_app"               # App 问答
    DB_QA = "chat_with_db_qa"      # DB 问答（旧模式）
    DASHBOARD = "chat_dashboard"   # 仪表盘

    @classmethod
    def values(cls) -> list[str]:
        return [m.value for m in cls]


def _clean_react_final(content: str) -> str:
    """清洗 ReAct Agent final_content 中可能泄露的非用户内容。

    场景：
      1. LLM 输出中包含 ````vis-thinking ... ```` 代码块（thinking trace 泄露）
      2. LLM 输出中包含原始 ReAct 格式残留（Thought:/Action:/Action Input:）
      3. terminate 工具执行失败时，final_content 是 LLM 原始输出而非提取的 result
         — 此时尝试从 Action Input 的 JSON 中提取 result 字段
    """
    if not content:
        return content

    s = content

    # 检测是否包含 ReAct 格式残留
    has_react_format = bool(re.search(
        r'(?:^|\n)\s*(?:Thought|Action|Action\s+Intention|Action\s+Reason|Action\s+Input)\s*:',
        s
    ))

    # 1. 去除 ````vis-thinking ... ```` 代码块（含 `````vis-thinking`）
    s = re.sub(r'`{3,6}vis-thinking\b.*?`{3,6}', '', s, flags=re.DOTALL)

    # 2. 去除 5/6 反引号包裹（LLM 有时会多包一层反引号）
    s = re.sub(r'`{5,6}\n?', '', s)

    if has_react_format:
        # 3. 尝试提取 Action Input: {"result": "..."} 中的 result
        #    Action Input 的值可能跨多行，JSON 中 result 值可能有大量转义
        #    用正则找到 "Action Input:" 后面的 JSON 对象
        ai_match = re.search(
            r'Action\s*Input\s*:\s*(\{.*\})\s*$',
            s,
            re.DOTALL
        )
        if ai_match:
            json_str = ai_match.group(1)
            # 尝试标准 JSON 解析
            try:
                ai_obj = json.loads(json_str)
                if "result" in ai_obj:
                    return ai_obj["result"]
            except (json.JSONDecodeError, ValueError):
                pass

            # JSON 解析失败，尝试用正则直接提取 "result" 字段的值
            # 匹配 "result": "..."（考虑转义引号）
            result_match = re.search(
                r'"result"\s*:\s*"((?:[^"\\]|\\.)*)"',
                json_str,
                re.DOTALL
            )
            if result_match:
                raw_result = result_match.group(1)
                # 反转义常见的 JSON 转义
                result = raw_result.replace('\\n', '\n').replace('\\t', '\t') \
                    .replace('\\"', '"').replace('\\\\', '\\')
                return result

        # 4. 如果 Action Input 提取失败但 content 确实是 ReAct 格式，
        #    尝试截取最后一个有意义的行（通常是 Observation 或直接文本）
        #    去除所有 ReAct 关键字行
        lines = s.split('\n')
        clean_lines = []
        react_keywords = ('Thought:', 'Action:', 'Action Intention:',
                          'Action Reason:', 'Action Input:', 'Observation:',
                          'Human:', 'Assistant:')
        for line in lines:
            stripped = line.strip()
            if any(stripped.startswith(kw) for kw in react_keywords):
                continue
            clean_lines.append(line)
        cleaned = '\n'.join(clean_lines).strip()
        if cleaned:
            s = cleaned

    # 5. 清理多余空行
    s = re.sub(r'\n{3,}', '\n\n', s).strip()

    return s

    return s


class QnAAgent:
    """核心问数 Agent。

    用法：
        agent = QnAAgent(client=client, model="TS-MOMA/DeepSeek-V4-Flash")
        result = await agent.ask("列出所有书名", datasource="chase_book")
    """

    def __init__(
        self,
        client: Client,
        model: str = "TS-MOMA/DeepSeek-V4-Flash",
        conv_uid: Optional[str] = None,
    ):
        self.client = client
        self.model = model
        self.conv_uid = conv_uid or str(uuid.uuid4())

    # ------------------------------------------------------------------
    # 对外主方法：统一问答（支持数据源 / 知识库 / Flow / 纯对话）
    # ------------------------------------------------------------------
    async def ask(
        self,
        question: str,
        chat_mode: Optional[str] = None,
        chat_param: Optional[str] = None,
        temperature: float = 0.2,
        max_new_tokens: int = 4000,
        normalize_mysql: bool = True,
    ) -> dict:
        """向 DB-GPT 提问，返回结构化结果。

        根据传入参数自动推断 chat_mode 和 chat_param：
          - chat_mode 显式指定时，直接使用
          - 未指定 chat_mode 但给了 chat_param → 按历史兼容逻辑推断
          - 两者都未给 → chat_normal（纯对话，不关联任何数据源/知识库）

        Args:
            question: 自然语言问题
            chat_mode: 问答模式（可选，见 ChatMode 枚举）
            chat_param: 数据源名 / 知识库名 / Flow UID（可选）
            temperature / max_new_tokens: LLM 采样参数
            normalize_mysql: 是否做 MySQL 双引号方言归一化

        Returns:
            {
                "ok": bool,
                "answer": str,         # 模型自然语言回答
                "sql": str,            # 模型生成并执行的 SQL
                "data": list|None,     # 执行结果
                "display_type": str,   # 展示类型
                "asked": bool,         # True=模型反问/未给出数据
                "conv_uid": str,
                "error": str,
            }
        """
        # 自动推断 chat_mode
        if chat_mode is None:
            if chat_param:
                chat_mode = ChatMode.DATA.value  # 有源默认走数据对话
            else:
                chat_mode = ChatMode.NORMAL.value  # 无源走纯对话
            normalize_mysql = False  # 非 chat_data 不做 SQL 归一化

        try:
            resp = await self.client.chat(
                model=self.model,
                messages=question,
                chat_mode=chat_mode,
                chat_param=chat_param,
                conv_uid=self.conv_uid,
                temperature=temperature,
                max_new_tokens=max_new_tokens,
            )
        except Exception as e:
            return self._err(f"调用 DB-GPT 异常: {e}")

        # 非 200 时 client.chat 返回 dict（含 error 字段）
        if isinstance(resp, dict):
            return self._err(f"DB-GPT 返回非 200: {resp}")

        try:
            content = resp.choices[0].message.content or ""
        except Exception as e:
            return self._err(f"响应解析异常: {e}")

        chart = self._parse_chart_view(content)
        sql = (chart or {}).get("sql", "")
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
    # 流式问答（支持数据源 / 知识库 / Flow / 纯对话）
    # ------------------------------------------------------------------
    async def ask_stream(
        self,
        question: str,
        chat_mode: Optional[str] = None,
        chat_param: Optional[str] = None,
        temperature: float = 0.2,
        max_new_tokens: int = 4000,
    ) -> AsyncGenerator[str, None]:
        """流式版本：逐个产出文本片段。"""
        if chat_mode is None:
            chat_mode = ChatMode.DATA.value if chat_param else ChatMode.NORMAL.value

        async for chunk in self.client.chat_stream(
            model=self.model,
            messages=question,
            chat_mode=chat_mode,
            chat_param=chat_param,
            conv_uid=self.conv_uid,
            temperature=temperature,
            max_new_tokens=max_new_tokens,
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
        self.conv_uid = str(uuid.uuid4())
        return self.conv_uid

    def set_session(self, conv_uid: str):
        self.conv_uid = conv_uid
        return self

    # ------------------------------------------------------------------
    # React Agent 流式问答（调用 DB-GPT /api/v1/chat/react-agent）
    # ------------------------------------------------------------------
    async def ask_react_stream(
        self,
        question: str,
        chat_param: Optional[str] = None,
        knowledge_space: Optional[str] = None,
        skill_name: Optional[str] = None,
        connector_ids: Optional[list] = None,
        database_name: Optional[str] = None,
        database_names: Optional[list] = None,
        file_ids: Optional[list] = None,
        temperature: float = 0.6,
        max_new_tokens: int = 4000,
        prompt_code: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """React Agent 流式问答（SSE 事件流）。

        调用 DB-GPT 原生 /api/v1/chat/react-agent，支持多步推理 + SQL 执行。
        当 database_names 包含多个数据源时，在调 DB-GPT 之前执行前置编排：
          - 工具1: 数据源选择（LLM 从候选库中选最合适的）
          - 工具2: 数据表选择（LLM 从选中库选相关表和字段）
        然后将选择结果注入 ext_info，继续委托 DB-GPT 完成 SQL 生成+执行。

        DB-GPT 通过 ext_info 承载以下可选资源（与 DB-GPT 前端一致）：
          - skill_name       : 预选 Skill（加载该技能的工具集）
          - database_name    : 数据库名（库路由）
          - knowledge_space  : 知识库名（database + knowledge 混合问答）
          - connector_ids    : 用户选中的 MCP 连接器 ID 列表（注入其工具）
          - file_ids         : 会话内已上传文件的 ID 列表（作为附件）

        Args:
            question: 自然语言问题
            chat_param: 数据源名（如 chase_double11，兼容旧接口）
            knowledge_space: 知识库名
            skill_name: Skill 名称（来自 GET /api/v1/skills/list）
            connector_ids: MCP 连接器 ID 列表
            database_name: 数据库名（优先级高于 chat_param）
            database_names: 多数据源列表（App 绑定多个时传入，触发前置选择）
            file_ids: 会话附件文件 ID 列表
            temperature / max_new_tokens: LLM 采样参数

        Yields:
            SSE 格式事件文本（data: {...}\n\n）
        """
        import httpx
        import os
        from modules.tool_orchestrator import ToolOrchestrator, make_tool_sse

        base = os.getenv("DBGPT_API_BASE", "http://127.0.0.1:5670/api/v2")
        # 确保 base 包含 /api/v2，否则添加
        if not base.endswith("/api/v2"):
            if "/api/v1" in base:
                base = base.replace("/api/v1", "/api/v2")
            elif not base.endswith("/api"):
                base = base.rstrip("/") + "/api/v2"
        react_url = base.replace("/api/v2", "/api/v1") + "/chat/react-agent"

        # ========== 前置编排：多数据源智能选择 ==========
        selected_ds = None
        table_hints = None

        if database_names and len(database_names) > 1:
            orchestrator = ToolOrchestrator(model=self.model)

            # --- 工具 1: 数据源选择 ---
            yield make_tool_sse("step.start", "datasource_select", {
                "tool_name": "数据源选择",
                "thought": f"从 {len(database_names)} 个候选数据源中选择最合适的一个",
            })

            try:
                ds_result = await orchestrator.select_datasource(question, database_names)
                selected_ds = ds_result.get("datasource", "")
                yield make_tool_sse("step.meta", "datasource_select", {
                    "tool_name": "数据源选择",
                    "result": ds_result,
                })
            except Exception as e:
                ds_result = {
                    "datasource": database_names[0],
                    "reason": f"工具异常: {e}",
                    "fallback": True,
                }
                selected_ds = database_names[0]
                yield make_tool_sse("step.meta", "datasource_select", {
                    "tool_name": "数据源选择",
                    "result": ds_result,
                    "error": str(e),
                })

            yield make_tool_sse("step.done", "datasource_select", {})

            # --- 工具 2: 数据表选择 ---
            if selected_ds:
                yield make_tool_sse("step.start", "table_select", {
                    "tool_name": "数据表选择",
                    "thought": f"从数据源 {selected_ds} 中选择相关数据表",
                })

                try:
                    tbl_result = await orchestrator.select_tables(question, selected_ds)
                    table_hints = tbl_result
                    yield make_tool_sse("step.meta", "table_select", {
                        "tool_name": "数据表选择",
                        "result": tbl_result,
                    })
                except Exception as e:
                    tbl_result = {
                        "tables": [],
                        "fields": {},
                        "reason": f"工具异常: {e}",
                        "fallback": True,
                    }
                    yield make_tool_sse("step.meta", "table_select", {
                        "tool_name": "数据表选择",
                        "result": tbl_result,
                        "error": str(e),
                    })

                yield make_tool_sse("step.done", "table_select", {})

        elif database_names and len(database_names) == 1:
            selected_ds = database_names[0]
            yield make_tool_sse("step.start", "datasource_select", {
                "tool_name": "数据源选择",
                "thought": "仅有一个数据源，直接使用",
            })
            yield make_tool_sse("step.meta", "datasource_select", {
                "tool_name": "数据源选择",
                "result": {"datasource": selected_ds, "reason": "仅有一个数据源，直接使用", "fallback": True},
            })
            yield make_tool_sse("step.done", "datasource_select", {})

        # ========== 委托 DB-GPT react-agent ==========
        final_db = selected_ds or database_name or chat_param or ""

        user_input = question
        prefix_parts = []
        if final_db:
            prefix_parts.append(f"[Database: {final_db}]")
        if table_hints and table_hints.get("tables"):
            tables_str = ",".join(table_hints["tables"])
            prefix_parts.append(f"[Tables: {tables_str}]")
        if prefix_parts:
            user_input = f"{' '.join(prefix_parts)} {question}"

        ext_info: dict = {}
        if final_db:
            ext_info["database_name"] = final_db
            ext_info["database_type"] = "mysql"
        if skill_name:
            ext_info["skill_name"] = skill_name
        if knowledge_space:
            ext_info["knowledge_space"] = knowledge_space
        if connector_ids:
            ext_info["connector_ids"] = list(connector_ids)
        if file_ids:
            ext_info["file_ids"] = list(file_ids)
        if prompt_code:
            ext_info["prompt_code"] = prompt_code

        body = {
            "conv_uid": self.conv_uid,
            "chat_mode": "chat_react_agent",
            "model_name": self.model,
            "user_input": user_input,
            "temperature": temperature,
            "max_new_tokens": max_new_tokens,
            "select_param": final_db or "",
            "ext_info": ext_info,
        }

        async with httpx.AsyncClient(timeout=float(os.getenv("TIMEOUT", "300")), trust_env=False) as c:
            async with c.stream("POST", react_url, json=body) as resp:
                if resp.status_code != 200:
                    error_text = await resp.aread()
                    yield f'data: {json.dumps({"type": "error", "message": f"DB-GPT {resp.status_code}: {error_text.decode()[:200]}"}, ensure_ascii=False)}\n\n'
                    return
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        payload = line[6:]
                        try:
                            evt = json.loads(payload)
                        except (json.JSONDecodeError, ValueError):
                            yield line + "\n\n"
                            continue

                        if evt.get("type") == "final":
                            content = evt.get("content", "")
                            if content:
                                cleaned = _clean_react_final(content)
                                if cleaned:
                                    evt["content"] = cleaned

                        yield f'data: {json.dumps(evt, ensure_ascii=False)}\n\n'

    # ------------------------------------------------------------------
    # Knowledge Agent 流式问答（调用 DB-GPT /api/v1/chat/knowledge-agent）
    # ------------------------------------------------------------------
    async def ask_knowledge_stream(
        self,
        question: str,
        chat_param: Optional[str] = None,
        file_ids: Optional[list] = None,
        temperature: float = 0.6,
        max_new_tokens: int = 4000,
    ) -> AsyncGenerator[str, None]:
        """Knowledge Agent 流式问答（SSE 事件流）。

        调用 DB-GPT 原生 /api/v1/chat/knowledge-agent，
        专用知识库检索 Agent，纯知识检索+引用，不带 SQL/Shell 工具。

        Args:
            question: 自然语言问题
            chat_param: 知识库名（如 csv）
            file_ids: 会话附件文件 ID 列表（可选，经 ext_info 注入）

        Yields:
            SSE 格式事件文本（data: {...}\n\n）
        """
        import httpx
        import os

        base = os.getenv("DBGPT_API_BASE", "http://127.0.0.1:5670/api/v2")
        ka_url = base.replace("/api/v2", "/api/v1") + "/chat/knowledge-agent"

        ext_info: dict = {}
        if file_ids:
            ext_info["file_ids"] = list(file_ids)

        body = {
            "conv_uid": self.conv_uid,
            "chat_mode": "chat_knowledge",
            "model_name": self.model,
            "user_input": question,
            "temperature": temperature,
            "max_new_tokens": max_new_tokens,
            "select_param": chat_param or "",
            "ext_info": ext_info,
        }

        async with httpx.AsyncClient(timeout=float(os.getenv("TIMEOUT", "300")), trust_env=False) as c:
            async with c.stream("POST", ka_url, json=body) as resp:
                if resp.status_code != 200:
                    error_text = await resp.aread()
                    yield f'data: {json.dumps({"type": "error", "message": f"DB-GPT {resp.status_code}: {error_text.decode()[:200]}"}, ensure_ascii=False)}\n\n'
                    return
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        yield line + "\n\n"

    # ------------------------------------------------------------------
    # 响应解析（与评测脚本同源）
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_chart_view(content: str):
        """从 LLM 响应中提取结构化数据。

        支持三种格式：
        1. <chart-view content="{...}" /> — DB-GPT 经典格式
        2. 裸 JSON（含 thoughts/sql/data/display_type 字段）
        3. 带 markdown 代码块的 JSON（```json ... ```）
        """
        if not content:
            return None

        # 1. <chart-view> 标签
        m = re.search(r"<chart-view\s+content=[\"'](.*?)[\"']\s*/>", content, re.S)
        if m:
            raw = html.unescape(m.group(1))
            try:
                return json.loads(raw)
            except Exception:
                pass

        # 2. markdown 代码块中的 JSON
        m2 = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.S)
        if m2:
            try:
                parsed = json.loads(m2.group(1))
                if "sql" in parsed or "data" in parsed or "thoughts" in parsed:
                    return parsed
            except Exception:
                pass

        # 3. 裸 JSON（整段内容就是 JSON）
        stripped = content.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                parsed = json.loads(stripped)
                # 只在包含关键字段时认为是结构化数据
                if "sql" in parsed or "data" in parsed or "thoughts" in parsed:
                    return parsed
            except Exception:
                pass

        # 4. 尝试从文本中提取第一个 JSON 对象
        m3 = re.search(r'\{[^{}]*"(?:sql|data|thoughts|direct_response|display_type)"[^{}]*\}', content, re.S)
        if m3:
            try:
                return json.loads(m3.group(0))
            except Exception:
                pass

        return None

    @staticmethod
    def _extract_plain(content: str) -> str:
        """剥离 chart-view / JSON 标签，只留纯文本回答。"""
        # 去掉 <chart-view>
        text = re.sub(r"<chart-view.*?/>", "", content, flags=re.S)
        # 去掉 markdown 代码块
        text = re.sub(r"```(?:json)?\s*\{.*?\}\s*```", "", text, flags=re.S)
        # 如果剩余文本是裸 JSON，尝试提取 direct_response
        stripped = text.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                parsed = json.loads(stripped)
                if "direct_response" in parsed:
                    return parsed.get("direct_response", "")
            except Exception:
                pass
        # 去掉其他 HTML 标签
        text = re.sub(r"<[^>]+>", "", text)
        return text.strip()

    @staticmethod
    def normalize_mysql_sql(sql: str) -> str:
        """MySQL 方言归一化（两步，避免误伤字符串值）。

        1) 等号/IN/括号后的 "值" 是字符串值 -> 转单引号 '值'
        2) 其余 "标识符"（列名/表名）-> 转反引号 `标识符`

        示例：
          SELECT "剧名" FROM "电视剧" WHERE 名称 = "东方卫视"
          -> SELECT `剧名` FROM `电视剧` WHERE 名称 = '东方卫视'
        """
        sql = re.sub(r'([=(,]\s*)"([^"]*)"', r"\1'\2'", sql)
        sql = re.sub(r'"([\w\u4e00-\u9fa5]+)"', r"`\1`", sql)
        return sql

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    @staticmethod
    def _err(msg: str) -> dict:
        return {
            "ok": False, "answer": "", "sql": "", "data": None,
            "display_type": "", "asked": False,
            "conv_uid": "", "error": msg,
        }
