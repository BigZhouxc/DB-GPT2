# -*- coding: utf-8 -*-
"""问答模块 —— 统一问答接口。

通过一个 /ask 接口，利用 chat_mode + chat_param 参数组合，
覆盖所有问答场景：
  - 数据对话（NL2SQL）：chat_mode=chat_data, chat_param=数据源名
  - 知识库问答：chat_mode=chat_knowledge, chat_param=知识库名
  - Flow 问答：chat_mode=chat_flow, chat_param=Flow UID
  - 纯对话：chat_mode=chat_normal, chat_param 不传
  - 自定义：chat_mode 用户指定，chat_param 对应参数

旧接口 /ask/knowledge、/ask/flow 保留向后兼容。
"""
import json
import os
from typing import Optional

import httpx
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core.client_factory import get_client
from core.qna_agent import ChatMode, QnAAgent
from core.session_manager import sessions

router = APIRouter(prefix="/ask", tags=["问答"])

MODEL = os.getenv("MODEL", "TS-MOMA/DeepSeek-V4-Flash")
DBGPT_API_BASE = os.getenv("DBGPT_API_BASE", "http://127.0.0.1:5670/api/v2")


# ---------------------------------------------------------------------------
# 辅助：获取 DB-GPT v1 API 完整 URL
# ---------------------------------------------------------------------------
def _v1_url(path: str) -> str:
    """构造 DB-GPT v1 API URL。"""
    base = DBGPT_API_BASE.replace("/api/v2", "/api/v1")
    return base.rstrip("/") + path


def _persist_binding_fire_and_forget(
    session: str,
    datasource_names: Optional[list] = None,
    knowledge_space: str = "",
    prompt_code: str = "",
):
    """把会话绑定的数据源/知识库落库到 chat_history（fire-and-forget，失败不影响问答）。

    保证会话恢复时 /conversations/{uid}/binding 能读回绑定信息，
    绑定状态不依赖前端内存记忆。
    """
    if not session:
        return
    names = [str(n).strip() for n in (datasource_names or []) if str(n).strip()]
    if not names and not knowledge_space and not prompt_code:
        return
    try:
        from modules.conversation import _update_conv_binding, _resolve_ids
        import asyncio

        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 在运行中的事件循环里用后台任务执行同步 DB 写（短事务，不阻塞）
            asyncio.ensure_future(_async_persist_binding(session, names, knowledge_space, prompt_code))
        else:
            asyncio.run(_async_persist_binding(session, names, knowledge_space, prompt_code))
    except Exception:
        # 绑定落库失败不影响问答主流程
        pass


async def _async_persist_binding(session: str, names: list, knowledge_space: str, prompt_code: str):
    """异步解析 ID 并写绑定（内部用线程池执行同步 pymysql 调用）。"""
    try:
        import asyncio as _asyncio
        from modules.conversation import _update_conv_binding, _resolve_ids

        def _do():
            ids = _resolve_ids(knowledge_space_name=knowledge_space or None)
            if names and "datasource_id" not in ids:
                import httpx as _httpx
                # 同步调用自己 /datasources 拿名称→ID 映射
                import urllib.request as _ur
                try:
                    r = _ur.urlopen("http://127.0.0.1:8080/datasources", timeout=8)
                    ds_list = json.loads(r.read().decode()).get("datasources", [])
                    for name in names:
                        for ds in ds_list:
                            if ds.get("db_name") == name:
                                ids["datasource_id"] = ds.get("id")
                                break
                        if "datasource_id" in ids:
                            break
                except Exception:
                    pass
            _update_conv_binding(
                session,
                datasource_id=ids.get("datasource_id"),
                knowledge_space_id=ids.get("knowledge_space_id"),
                prompt_code=prompt_code or None,
            )

        await _asyncio.get_event_loop().run_in_executor(None, _do)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Pydantic 请求模型
# ---------------------------------------------------------------------------
class AskRequest(BaseModel):
    """统一问答请求。

    通过 chat_mode + chat_param 组合控制问答模式：
      - 不传 chat_mode 且不传 chat_param → 纯对话（chat_normal）
      - 不传 chat_mode 但传 chat_param → 数据对话（chat_data，历史兼容）
      - 传 chat_mode=chat_knowledge + chat_param=知识库名 → 知识库问答
      - 传 chat_mode=chat_flow + chat_param=Flow UID → Flow 问答
      - 传 chat_mode=chat_normal 且不传 chat_param → 纯对话
    """
    question: str = Field(..., description="自然语言问题")
    chat_mode: Optional[str] = Field(
        None,
        description="问答模式（可选）。不传时自动推断：有 chat_param 走 chat_data，无 chat_param 走 chat_normal"
    )
    chat_param: Optional[str] = Field(
        None,
        description="问答参数（可选）。数据源名 / 知识库名 / Flow UID，取决于 chat_mode"
    )
    session: str = Field("", description="会话 ID（可选，缺省自动管理）")
    temperature: float = Field(0.2, description="温度参数")
    max_new_tokens: int = Field(4000, description="最大 token 数")
    normalize_mysql: Optional[bool] = Field(
        None,
        description="是否做 MySQL 方言归一化（可选，默认：chat_data 模式 True，其他 False）"
    )


class StreamAskRequest(BaseModel):
    """统一流式问答请求。"""
    question: str = Field(..., description="自然语言问题")
    chat_mode: Optional[str] = Field(None, description="问答模式（可选，自动推断）")
    chat_param: Optional[str] = Field(None, description="问答参数（可选）")
    session: str = Field("", description="会话 ID（可选）")
    temperature: float = Field(0.2, description="温度参数")
    max_new_tokens: int = Field(4000, description="最大 token 数")


class SessionRequest(BaseModel):
    key: str = Field(..., description="会话标识（数据源名或自定义 key）")


# ---------------------------------------------------------------------------
# 辅助：获取/创建 Agent
# ---------------------------------------------------------------------------
def _get_agent(chat_param: str, session: str = "", model_name: Optional[str] = None) -> QnAAgent:
    """根据 chat_param（可能为 None）获取 Agent。"""
    client = get_client()
    use_model = model_name or MODEL
    agent = QnAAgent(client=client, model=use_model)
    if session:
        agent.set_session(session)
    else:
        # 用 chat_param 或 "default" 作为会话池 key
        key = chat_param or "default"
        agent.set_session(sessions.get_or_create(key))
    return agent


def _resolve_normalize(req: AskRequest) -> bool:
    """确定是否做 MySQL 归一化。"""
    if req.normalize_mysql is not None:
        return req.normalize_mysql
    # 默认：chat_data 做，其他不做
    mode = req.chat_mode
    if mode is None:
        mode = ChatMode.DATA.value if req.chat_param else ChatMode.NORMAL.value
    return mode == ChatMode.DATA.value


# ---------------------------------------------------------------------------
# 接口
# ---------------------------------------------------------------------------
@router.get("/chat-modes")
async def list_chat_modes():
    """列出所有支持的问答模式。"""
    return {
        "ok": True,
        "modes": [{"value": m.value, "name": m.name} for m in ChatMode],
    }


@router.post("/scenes")
async def list_scenes():
    """从 DB-GPT 动态获取对话场景列表。

    对应 DB-GPT 原生 POST /api/v1/chat/dialogue/scenes。
    返回所有可用对话场景（chat_with_db_execute / chat_excel / chat_knowledge 等）。
    """
    try:
        async with httpx.AsyncClient(timeout=10, trust_env=False) as c:
            resp = await c.post(_v1_url("/chat/dialogue/scenes"))
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success") or data.get("status") == "ok":
                    scenes = data.get("sys_text", [])
                    if not scenes:
                        scenes = data.get("data", data.get("items", []))
                    return {"ok": True, "scenes": scenes}
                return {"ok": True, "scenes": data}
            return {"ok": False, "error": f"DB-GPT {resp.status_code}", "scenes": []}
    except Exception as e:
        return {"ok": False, "error": str(e), "scenes": []}


@router.post("/mode-params")
async def list_mode_params(chat_mode: str = ""):
    """从 DB-GPT 动态获取指定模式的可选参数列表。

    对应 DB-GPT 原生 POST /api/v1/chat/mode/params/list?chat_mode=xxx。
    返回该模式下的可选参数（如 chat_data 返回数据源列表，chat_knowledge 返回知识库列表）。
    """
    try:
        url = _v1_url(f"/chat/mode/params/list?chat_mode={chat_mode}")
        async with httpx.AsyncClient(timeout=10, trust_env=False) as c:
            resp = await c.post(url)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success") or data.get("status") == "ok":
                    params = data.get("sys_text", [])
                    if not params:
                        params = data.get("data", data.get("items", []))
                    return {"ok": True, "params": params}
                return {"ok": True, "params": data}
            return {"ok": False, "error": f"DB-GPT {resp.status_code}", "params": []}
    except Exception as e:
        return {"ok": False, "error": str(e), "params": []}


@router.get("/skills")
async def list_skills():
    """列出 DB-GPT 可用的所有 Skill。

    代理 DB-GPT 原生 GET /api/v1/skills/list。
    返回技能元数据（id / name / description / skill_type / type 等），
    供前端"技能选择"下拉使用，并在 react-agent 中通过 ext_info.skill_name 注入。
    """
    try:
        async with httpx.AsyncClient(timeout=10, trust_env=False) as c:
            resp = await c.get(_v1_url("/skills/list"))
            if resp.status_code == 200:
                data = resp.json()
                skills = data.get("data") or []
                if not isinstance(skills, list):
                    skills = []
                return {"ok": True, "skills": skills}
            return {"ok": False, "error": f"DB-GPT {resp.status_code}", "skills": []}
    except Exception as e:
        return {"ok": False, "error": str(e), "skills": []}


@router.get("/skills/detail")
async def skill_detail(skill_name: str = "", file_path: str = ""):
    """查看技能详情（SKILL.md 内容、文件树、元数据）。

    代理 DB-GPT GET /api/v1/skills/detail?skill_name=xxx&file_path=xxx。
    """
    try:
        params = {}
        if skill_name:
            params["skill_name"] = skill_name
        if file_path:
            params["file_path"] = file_path
        async with httpx.AsyncClient(timeout=15, trust_env=False) as c:
            resp = await c.get(_v1_url("/skills/detail"), params=params)
            if resp.status_code == 200:
                data = resp.json()
                return {"ok": True, "detail": data.get("data", data)}
            return {"ok": False, "error": f"DB-GPT {resp.status_code}", "detail": None}
    except Exception as e:
        return {"ok": False, "error": str(e), "detail": None}


@router.post("/skills/upload")
async def skill_upload(file: UploadFile = File(...)):
    """上传技能包（.zip / .skill / 单文件）到 DB-GPT。

    代理 DB-GPT POST /api/v1/skills/upload（multipart）。
    """
    try:
        content = await file.read()
        async with httpx.AsyncClient(timeout=60, trust_env=False) as c:
            resp = await c.post(
                _v1_url("/skills/upload"),
                files={"file": (file.filename or "skill.zip", content,
                                file.content_type or "application/octet-stream")},
            )
            data = resp.json()
            if resp.status_code == 200 and data.get("success"):
                return {"ok": True, "result": data.get("data", data)}
            return {"ok": False, "error": data.get("err_msg") or str(data)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("")
@router.post("/")
async def ask(req: AskRequest):
    """统一问答接口。

    通过 chat_mode + chat_param 组合，覆盖所有问答场景：
    - 数据对话（NL2SQL）
    - 知识库问答
    - Flow 问答
    - 纯对话（不传任何源）
    """
    agent = _get_agent(req.chat_param or "", req.session)
    result = await agent.ask(
        question=req.question,
        chat_mode=req.chat_mode,
        chat_param=req.chat_param,
        temperature=req.temperature,
        max_new_tokens=req.max_new_tokens,
        normalize_mysql=_resolve_normalize(req),
    )
    return result


@router.post("/stream")
async def ask_stream(req: StreamAskRequest):
    """统一流式问答接口（SSE）。

    通过 SDK chat_stream 获取逐字 delta，包装成 JSON 事件返回。
    适用于纯对话场景（无工具/数据源），获得真正的逐字流式输出。

    SSE 事件：
      data: {"type":"chunk","content":"文本片段"}
      data: {"type":"done"}
      data: [DONE]
    """
    agent = _get_agent(req.chat_param or "", req.session)

    async def gen():
        try:
            async for text in agent.ask_stream(
                req.question,
                chat_mode=req.chat_mode,
                chat_param=req.chat_param,
                temperature=req.temperature,
                max_new_tokens=req.max_new_tokens,
            ):
                if text:
                    yield f"data: {json.dumps({'type': 'chunk', 'content': text}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


class ReactAgentRequest(BaseModel):
    """React Agent 流式问答请求。"""
    question: str = Field(..., description="自然语言问题")
    chat_param: Optional[str] = Field(
        None,
        description="数据源名（如 chase_double11）。不传则纯对话模式。"
    )
    knowledge_space: Optional[str] = Field(
        None,
        description="知识库名（可选）。与 chat_param 同时传入时，React Agent 同时拥有 SQL 和知识库检索能力。"
    )
    skill_name: Optional[str] = Field(
        None,
        description="Skill 名称（可选，来自 GET /ask/skills）。预选技能以加载对应工具集。"
    )
    connector_ids: Optional[list] = Field(
        None,
        description="MCP 连接器 ID 列表（可选）。将所选连接器的工具注入 Agent。"
    )
    database_name: Optional[str] = Field(
        None,
        description="数据库名（可选，优先级高于 chat_param，用于库路由）。"
    )
    database_names: Optional[list] = Field(
        None,
        description="多数据源名称列表（可选）。传入多个时触发前置数据源+数据表智能选择工具。"
    )
    file_ids: Optional[list] = Field(
        None,
        description="会话附件文件 ID 列表（可选，来自 POST /files/upload）。"
    )
    session: str = Field("", description="会话 ID（可选，缺省自动管理）")
    temperature: float = Field(0.6, description="温度参数")
    max_new_tokens: int = Field(4000, description="最大 token 数")
    prompt_code: Optional[str] = Field(None, description="自定义提示词的 prompt_code（从 App 配置传入）")
    model_name: Optional[str] = Field(None, description="模型名称（可选，覆盖默认模型）")


@router.post("/react-agent")
async def ask_react_agent(req: ReactAgentRequest):
    """React Agent 流式问答接口（SSE）。

    调用 DB-GPT 原生 react-agent，支持多步推理 + SQL 执行 + 结果返回。
    这是 DB-GPT 前端使用的接口，能实际执行 SQL 并返回结果数据。

    SSE 事件类型：
    - context.status: 上下文预算
    - step.start: 推理步骤开始
    - step.meta: 步骤元信息（thought / action / action_input）
    - step.chunk: 步骤输出内容（markdown 格式表格）
    - step.done: 步骤完成
    - final: 最终回答
    - done: 流结束
    - error: 错误
    """
    agent = _get_agent(req.chat_param or req.knowledge_space or "", req.session, model_name=req.model_name)

    # ★ 服务端兜底：把本次会话选中的数据源/知识库落库到 chat_history 绑定字段，
    #   会话恢复时 /conversations/{uid}/binding 才能读回（不依赖前端记忆）
    _persist_binding_fire_and_forget(
        req.session,
        datasource_names=(req.database_names or ([req.chat_param] if req.chat_param else [])
                          or ([req.database_name] if req.database_name else [])),
        knowledge_space=req.knowledge_space or "",
        prompt_code=req.prompt_code or "",
    )

    async def gen():
        try:
            async for sse_line in agent.ask_react_stream(
                question=req.question,
                chat_param=req.chat_param,
                knowledge_space=req.knowledge_space,
                skill_name=req.skill_name,
                connector_ids=req.connector_ids,
                database_name=req.database_name,
                database_names=req.database_names,
                file_ids=req.file_ids,
                temperature=req.temperature,
                max_new_tokens=req.max_new_tokens,
                prompt_code=req.prompt_code,
            ):
                yield sse_line
        except Exception as e:
            import json as _json
            yield f'data: {_json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False)}\n\n'

    return StreamingResponse(gen(), media_type="text/event-stream")


class KnowledgeAgentRequest(BaseModel):
    """Knowledge Agent 流式问答请求。"""
    question: str = Field(..., description="自然语言问题")
    chat_param: Optional[str] = Field(
        None,
        description="知识库名（如 csv）。不传则走默认知识库。"
    )
    file_ids: Optional[list] = Field(
        None,
        description="会话附件文件 ID 列表（可选，来自 POST /files/upload）。"
    )
    session: str = Field("", description="会话 ID（可选）")
    temperature: float = Field(0.6, description="温度参数")
    max_new_tokens: int = Field(4000, description="最大 token 数")


@router.post("/knowledge-agent")
async def ask_knowledge_agent(req: KnowledgeAgentRequest):
    """Knowledge Agent 流式问答接口（SSE）。

    调用 DB-GPT 原生 knowledge-agent，纯知识库检索 + 引用回答。
    与 react-agent 区别：不带 SQL/Shell 工具，专注知识库检索。

    SSE 事件格式同 react-agent。
    """
    agent = _get_agent(req.chat_param or "", req.session)

    async def gen():
        try:
            async for sse_line in agent.ask_knowledge_stream(
                question=req.question,
                chat_param=req.chat_param,
                file_ids=req.file_ids,
                temperature=req.temperature,
                max_new_tokens=req.max_new_tokens,
            ):
                yield sse_line
        except Exception as e:
            yield f'data: {json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False)}\n\n'

    return StreamingResponse(gen(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# 向后兼容旧接口（保留但不推荐使用，统一走 /ask）
# ---------------------------------------------------------------------------
@router.post("/knowledge", deprecated=True)
async def ask_knowledge_legacy(
    question: str = "",
    space_name: str = "",
    session: str = "",
    temperature: float = 0.2,
    max_new_tokens: int = 4000,
):
    """[已废弃] 知识库问答。请使用 POST /ask，传 chat_mode=chat_knowledge, chat_param=空间名。"""
    agent = _get_agent(space_name, session)
    result = await agent.ask(
        question=question,
        chat_mode=ChatMode.KNOWLEDGE.value,
        chat_param=space_name,
        temperature=temperature,
        max_new_tokens=max_new_tokens,
        normalize_mysql=False,
    )
    return result


@router.post("/flow", deprecated=True)
async def ask_flow_legacy(
    question: str = "",
    flow_uid: str = "",
    session: str = "",
    temperature: float = 0.2,
    max_new_tokens: int = 4000,
):
    """[已废弃] Flow 问答。请使用 POST /ask，传 chat_mode=chat_flow, chat_param=Flow UID。"""
    agent = _get_agent(flow_uid, session)
    result = await agent.ask(
        question=question,
        chat_mode=ChatMode.FLOW.value,
        chat_param=flow_uid,
        temperature=temperature,
        max_new_tokens=max_new_tokens,
        normalize_mysql=False,
    )
    return result


# ---------------------------------------------------------------------------
# 会话管理
# ---------------------------------------------------------------------------
@router.post("/session/new")
async def new_session(req: SessionRequest):
    """为指定标识新建会话。"""
    conv = sessions.new(req.key)
    return {"ok": True, "key": req.key, "session": conv}


@router.get("/sessions")
async def list_sessions():
    """列出所有会话映射。"""
    return {"ok": True, "sessions": sessions.list()}


@router.delete("/sessions/{key}")
async def remove_session(key: str):
    """移除指定会话。"""
    sessions.remove(key)
    return {"ok": True, "removed": key}


@router.post("/sessions/reset")
async def reset_sessions():
    """清空所有会话。"""
    sessions.reset()
    return {"ok": True, "cleared": True}
