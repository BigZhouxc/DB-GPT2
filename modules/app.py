# -*- coding: utf-8 -*-
"""App 管理模块 —— 类 Dify 应用模式。

App = 配置模板（创建时绑定数据源/知识库，之后不可变）
对话 = 每次新建会话，历史可恢复
对话中可变 = 技能/MCP/本地文件（不影响 App 配置）
"""
import json
from typing import List, Optional

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core.client_factory import get_client
from core.qna_agent import QnAAgent
from core.session_manager import sessions

router = APIRouter(prefix="/apps", tags=["App 管理"])

_DBGPT_V1_BASE = "http://db-gpt-webserver-1:5670/api/v1"


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------
class AppCreateRequest(BaseModel):
    app_name: str = Field(..., description="应用名称")
    app_describe: str = Field("", description="应用描述")
    chat_mode: str = Field("chat_react_agent", description="对话模式：chat_normal/chat_with_db_execute/chat_with_db_qa/chat_dashboard/chat_excel/chat_knowledge/chat_flow/chat_react_agent/chat_knowledge_agent")
    database_name: str = Field("", description="绑定的数据源（创建后不可变）")
    knowledge_space: str = Field("", description="绑定的知识库（创建后不可变）")
    model: str = Field("TS/GLM-5.2", description="模型")
    temperature: float = Field(0.6, description="温度")
    max_new_tokens: int = Field(4000, description="最大 token")
    recommend_questions: List[str] = Field(default_factory=list, description="推荐问题")
    prompt_template: str = Field("", description="自定义提示词名称（追加到默认 system prompt）")


class AppEditRequest(BaseModel):
    """编辑应用配置——数据源/知识库保持原值，可改 chat_mode/模型/推荐问题。"""
    app_name: str = Field("", description="应用名称")
    app_describe: str = Field("", description="应用描述")
    chat_mode: str = Field("chat_react_agent", description="对话模式")
    database_name: str = Field("", description="数据源（编辑时忽略，保持原值）")
    knowledge_space: str = Field("", description="知识库（编辑时忽略，保持原值）")
    model: str = Field("TS/GLM-5.2", description="模型")
    temperature: float = Field(0.6, description="温度")
    max_new_tokens: int = Field(4000, description="最大 token")
    recommend_questions: List[str] = Field(default_factory=list, description="推荐问题")
    prompt_template: str = Field("", description="自定义提示词名称（追加到默认 system prompt）")


class AppChatRequest(BaseModel):
    question: str = Field(..., description="自然语言问题")
    conv_uid: str = Field("", description="会话 ID（空=新建会话，非空=继续历史会话）")
    # 对话中可变
    skill_name: Optional[str] = Field(None, description="技能（对话中可改）")
    connector_ids: Optional[List[str]] = Field(None, description="MCP 连接器（对话中可改）")
    file_ids: Optional[List] = Field(None, description="上传文件 ID（对话中可改）")
    temperature: Optional[float] = Field(None, description="温度（覆盖）")
    max_new_tokens: Optional[int] = Field(None, description="最大 token（覆盖）")


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------
async def _v1_post(path, body):
    async with httpx.AsyncClient(timeout=30, trust_env=False) as c:
        r = await c.post(f"{_DBGPT_V1_BASE}{path}", json=body)
        return r.json()

async def _v1_get(path):
    async with httpx.AsyncClient(timeout=30, trust_env=False) as c:
        r = await c.get(f"{_DBGPT_V1_BASE}{path}")
        return r.json()

async def _v1_new_conv():
    async with httpx.AsyncClient(timeout=15, trust_env=False) as c:
        r = await c.post(f"{_DBGPT_V1_BASE}/chat/dialogue/new", json={"user_name": "", "sys_code": ""})
        d = r.json()
        if d.get("success"):
            return d.get("data", {}).get("conv_uid", "")
        return ""

def _build_app_body(req):
    resources = []
    if req.database_name:
        resources.append({"type": "database", "name": "数据源", "value": json.dumps({"name": "datasource", "db_name": req.database_name}, ensure_ascii=False), "is_dynamic": False, "context": None, "version": "v2"})
    if req.knowledge_space:
        resources.append({"type": "knowledge", "name": "知识库", "value": json.dumps({"name": "knowledge", "knowledge_space": req.knowledge_space}, ensure_ascii=False), "is_dynamic": False, "context": None, "version": "v2"})
    # chat_mode 映射到 DB-GPT 的 team_mode + team_context
    # native_app 模式 + team_context.chat_scene = chat_mode
    return {
        "app_name": req.app_name,
        "app_describe": req.app_describe,
        "language": "zh",
        "team_mode": "native_app",
        "team_context": json.dumps({"chat_scene": req.chat_mode}),
        "published": "true",
        "param_need": [{"type": "resource"}, {"type": "model"}, {"type": "temperature"}, {"type": "max_new_tokens"}],
        "details": [{
            "agent_name": "ReAct",
            "resources": resources,
            "llm_strategy": "Priority",
            "llm_strategy_value": req.model,
            "prompt_template": req.prompt_template,
            "temperate": req.temperature,
            "max_new_tokens": req.max_new_tokens,
        }],
    }

def _extract_resources(app_detail):
    res = {"database_name": "", "knowledge_space": "", "model": "", "chat_mode": "chat_react_agent", "prompt_template": ""}
    # 从 team_context 提取 chat_mode
    tc = app_detail.get("team_context")
    if tc:
        try:
            if isinstance(tc, str):
                tc_parsed = json.loads(tc)
            else:
                tc_parsed = tc
            res["chat_mode"] = tc_parsed.get("chat_scene", "chat_react_agent")
        except Exception:
            pass
    for detail in app_detail.get("details") or []:
        for r in detail.get("resources") or []:
            rtype = r.get("type", "")
            rval = r.get("value", "")
            try:
                parsed = json.loads(rval) if isinstance(rval, str) and rval.startswith("{") else {}
            except Exception:
                parsed = {}
            if rtype in ("database", "datasource") and not res["database_name"]:
                res["database_name"] = parsed.get("db_name") or rval
            elif rtype == "knowledge" and not res["knowledge_space"]:
                res["knowledge_space"] = parsed.get("knowledge_space") or rval
        lsv = detail.get("llm_strategy_value")
        if lsv and not res["model"]:
            try:
                if isinstance(lsv, str) and lsv.startswith("["):
                    arr = json.loads(lsv)
                    res["model"] = arr[0] if arr else str(lsv)
                else:
                    res["model"] = str(lsv)
            except Exception:
                res["model"] = str(lsv)
        # 提取 prompt_template
        pt = detail.get("prompt_template")
        if pt and not res["prompt_template"]:
            res["prompt_template"] = pt
    return res


# ---------------------------------------------------------------------------
# App CRUD（无 edit——资源创建后不可变）
# ---------------------------------------------------------------------------
@router.get("")
@router.get("/")
async def list_apps():
    """列出所有 App。"""
    try:
        data = await _v1_post("/app/list", {})
        if not data.get("success"):
            raise HTTPException(400, detail=str(data.get("err_msg", data)))
        raw = data.get("data") or {}
        raw_apps = raw.get("app_list") if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
        apps = []
        for a in raw_apps or []:
            apps.append({
                "app_code": a.get("app_code"),
                "app_name": a.get("app_name"),
                "app_describe": a.get("app_describe"),
                "team_mode": a.get("team_mode"),
                "published": a.get("published"),
            })
        return {"ok": True, "apps": apps}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"获取 App 列表失败: {e}")


@router.get("/{app_code}")
async def get_app_detail(app_code: str):
    """获取 App 详情（含绑定资源 + 推荐问题，只读）。"""
    try:
        data = await _v1_get(f"/app/{app_code}")
        if not data.get("success"):
            raise HTTPException(404, detail=f"App 不存在")
        app = data.get("data") or {}
        res = _extract_resources(app)
        rqs = [q.get("question", "") for q in app.get("recommend_questions") or []]
        return {
            "ok": True,
            "app": {
                "app_code": app.get("app_code"),
                "app_name": app.get("app_name"),
                "app_describe": app.get("app_describe"),
                "published": app.get("published"),
                "resources": res,
                "recommend_questions": rqs,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"获取 App 详情失败: {e}")


@router.post("")
@router.post("/")
async def create_app(req: AppCreateRequest):
    """创建应用（绑定数据源/知识库，创建后不可变）。"""
    try:
        body = _build_app_body(req)
        data = await _v1_post("/app/create", body)
        if not data.get("success"):
            err_msg = str(data.get("err_msg", data))
            # 友好化常见错误
            if "Duplicate entry" in err_msg and "app_name" in err_msg.lower():
                err_msg = f"应用名已存在，请换一个名称"
            elif "Duplicate entry" in err_msg:
                err_msg = f"应用名重复，请换一个名称"
            raise HTTPException(400, detail=err_msg)
        app = data.get("data") or {}
        return {"ok": True, "app": {"app_code": app.get("app_code"), "app_name": app.get("app_name")}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"创建 App 失败: {e}")


@router.delete("/{app_code}")
async def delete_app(app_code: str):
    """删除应用。"""
    try:
        data = await _v1_post("/app/remove", {"app_code": app_code})
        if not data.get("success"):
            raise HTTPException(400, detail=str(data.get("err_msg", data)))
        return {"ok": True, "app_code": app_code}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"删除 App 失败: {e}")


@router.post("/{app_code}/edit")
async def edit_app(app_code: str, req: AppEditRequest):
    """编辑应用配置——保留原有数据源/知识库，更新 chat_mode/模型/推荐问题。"""
    try:
        # 1. 先获取当前 app 详情，提取原有 resources
        detail_data = await _v1_get(f"/app/{app_code}")
        if not detail_data.get("success"):
            raise HTTPException(404, detail=f"App 不存在")
        app_detail = detail_data.get("data") or {}
        old_res = _extract_resources(app_detail)

        # 2. 数据源/知识库：请求传了新值则用新值，空值保持原值
        db_name = req.database_name if req.database_name else old_res.get("database_name", "")
        kb_name = req.knowledge_space if req.knowledge_space else old_res.get("knowledge_space", "")
        # prompt_template：空值保持原值
        pt_name = req.prompt_template if req.prompt_template else old_res.get("prompt_template", "")
        resources = []
        if db_name:
            resources.append({"type": "database", "name": "数据源", "value": json.dumps({"name": "datasource", "db_name": db_name}, ensure_ascii=False), "is_dynamic": False, "context": None, "version": "v2"})
        if kb_name:
            resources.append({"type": "knowledge", "name": "知识库", "value": json.dumps({"name": "knowledge", "knowledge_space": kb_name}, ensure_ascii=False), "is_dynamic": False, "context": None, "version": "v2"})

        body = {
            "app_code": app_code,
            "app_name": req.app_name,
            "app_describe": req.app_describe,
            "language": "zh",
            "team_mode": "native_app",
            "team_context": json.dumps({"chat_scene": req.chat_mode}),
            "published": "true",
            "param_need": [{"type": "resource"}, {"type": "model"}, {"type": "temperature"}, {"type": "max_new_tokens"}],
            "details": [{
                "agent_name": "ReAct",
                "resources": resources,
                "llm_strategy": "Priority",
                "llm_strategy_value": req.model,
                "prompt_template": pt_name,
                "temperate": req.temperature,
                "max_new_tokens": req.max_new_tokens,
            }],
        }
        data = await _v1_post("/app/edit", body)
        if not data.get("success"):
            raise HTTPException(400, detail=str(data.get("err_msg", data)))
        return {"ok": True, "app_code": app_code}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"修改 App 失败: {e}")


# ---------------------------------------------------------------------------
# 会话管理
# ---------------------------------------------------------------------------
@router.get("/{app_code}/sessions")
async def list_sessions(app_code: str):
    """列出该应用的所有历史会话。"""
    try:
        data = await _v1_get("/chat/dialogue/list")
        if not data.get("success"):
            raise HTTPException(400, detail=str(data.get("err_msg")))
        all_convs = data.get("data") or []
        # DB-GPT 的会话里 app_code 在 summary 或需要按 app_code 过滤
        # 目前 DB-GPT /list 不直接按 app_code 过滤，返回全部让前端筛选
        sessions = []
        for conv in all_convs:
            c = {
                "conv_uid": conv.get("conv_uid"),
                "summary": conv.get("summary", ""),
                "app_code": conv.get("app_code", ""),
                "user_name": conv.get("user_name", ""),
                "gmt_created": conv.get("gmt_created", ""),
            }
            # 只返回匹配当前 app 的会话
            if c["app_code"] == app_code or not c["app_code"]:
                sessions.append(c)
        return {"ok": True, "sessions": sessions}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"获取会话列表失败: {e}")


# ---------------------------------------------------------------------------
# 基于应用对话（对话隔离核心）
# ---------------------------------------------------------------------------
@router.post("/{app_code}/chat")
async def chat_with_app(app_code: str, req: AppChatRequest):
    """基于应用对话（SSE）。

    1. 查 App → 获取绑定资源（数据源/知识库，不可变）
    2. 新建或复用 conv_uid（对话隔离）
    3. 注入 ext_info → 调 react-agent
    4. 技能/MCP/文件由请求传（对话中可变）
    """
    try:
        detail_data = await _v1_get(f"/app/{app_code}")
        if not detail_data.get("success"):
            raise HTTPException(404, detail=f"App {app_code} 不存在")
        app_detail = detail_data.get("data") or {}
        res = _extract_resources(app_detail)
        chat_mode = res.get("chat_mode", "chat_react_agent")

        # 会话隔离
        conv_uid = req.conv_uid
        if not conv_uid:
            conv_uid = await _v1_new_conv()
            if not conv_uid:
                conv_uid = f"app_{app_code}"

        session_key = f"app:{app_code}:{conv_uid}"
        agent = QnAAgent()
        agent.set_session(sessions.get_or_create(session_key))

        db_name = res.get("database_name", "")
        kb_name = res.get("knowledge_space", "")

        async def gen():
            try:
                yield f'data: {json.dumps({"type": "conv_uid", "conv_uid": conv_uid}, ensure_ascii=False)}\n\n'
                # 按 chat_mode 路由
                if chat_mode in ("chat_react_agent", "react_agent"):
                    async for sse_line in agent.ask_react_stream(
                        question=req.question,
                        chat_param=db_name,
                        knowledge_space=kb_name or None,
                        skill_name=req.skill_name,
                        connector_ids=req.connector_ids,
                        database_name=db_name or None,
                        file_ids=req.file_ids,
                        temperature=req.temperature or 0.6,
                        max_new_tokens=req.max_new_tokens or 4000,
                    ):
                        yield sse_line
                elif chat_mode in ("chat_knowledge_agent", "knowledge_agent"):
                    async for sse_line in agent.ask_knowledge_stream(
                        question=req.question,
                        knowledge_space=kb_name,
                        file_ids=req.file_ids,
                    ):
                        yield sse_line
                else:
                    # 其他 chat_mode 走 react-agent（带数据库）
                    async for sse_line in agent.ask_react_stream(
                        question=req.question,
                        chat_param=db_name,
                        knowledge_space=kb_name or None,
                        skill_name=req.skill_name,
                        connector_ids=req.connector_ids,
                        database_name=db_name or None,
                        file_ids=req.file_ids,
                        temperature=req.temperature or 0.6,
                        max_new_tokens=req.max_new_tokens or 4000,
                    ):
                        yield sse_line
            except Exception as e:
                yield f'data: {json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False)}\n\n'

        return StreamingResponse(gen(), media_type="text/event-stream")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"应用对话失败: {e}")
