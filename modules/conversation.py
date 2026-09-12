# -*- coding: utf-8 -*-
"""会话管理模块 —— 使用 DB-GPT v1 API（非 serve 路由）。

DB-GPT 的会话管理在 /api/v1/chat/dialogue/ 下，不在 serve 路由下。
SDK 的 client.get(path) 会拼成 /api/v2/serve{path}，无法直接用于 v1 API。
所以这里用 httpx 直接请求 v1 路径。
"""
import os
from typing import Optional

import httpx
import pymysql
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/conversations", tags=["会话管理"])

# DB-GPT API 地址
DBGPT_BASE = os.getenv("DBGPT_API_BASE", "http://127.0.0.1:5670/api/v2")
# v1 会话 API 前缀
_DIALOGUE_BASE = DBGPT_BASE.replace("/api/v2", "/api/v1") + "/chat/dialogue"

# MySQL 连接配置
_MYSQL_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "db-gpt-db-1"),
    "port": int(os.getenv("MYSQL_PORT", "3306")),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", "aa123456"),
    "database": os.getenv("MYSQL_DATABASE", "dbgpt"),
    "charset": "utf8mb4",
}


def _resolve_ids(datasource_name: str = None, knowledge_space_name: str = None) -> dict:
    """将数据源/知识库名称解析为 ID。"""
    result = {}
    conn = pymysql.connect(**_MYSQL_CONFIG)
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            if datasource_name:
                # 数据源通过 DB-GPT serve API 管理，名称在 db_name 字段
                # 尝试从 dbgpt_serve_datasource 或直接查 serve 接口
                # 这里通过 qna_agent 自己的 datasource API 查
                pass
            if knowledge_space_name:
                cursor.execute("SELECT id FROM knowledge_space WHERE name = %s", (knowledge_space_name,))
                row = cursor.fetchone()
                if row:
                    result["knowledge_space_id"] = row["id"]
    finally:
        conn.close()
    return result


def _update_conv_binding(conv_uid: str, datasource_id: int = None, knowledge_space_id: int = None, prompt_code: str = None, status: str = None):
    """更新会话绑定的数据源/知识库/提示词/状态（写入 chat_history 表）。
    chat_history 记录可能在创建会话时还不存在（DB-GPT 在首次发消息后才插入），
    所以用 INSERT ... ON DUPLICATE KEY UPDATE 兼容两种情况。
    """
    fields, values = [], []
    if datasource_id is not None:
        fields.append("datasource_id = %s"); values.append(datasource_id)
    if knowledge_space_id is not None:
        fields.append("knowledge_space_id = %s"); values.append(knowledge_space_id)
    if prompt_code is not None:
        fields.append("prompt_code = %s"); values.append(prompt_code)
    if status is not None:
        fields.append("status = %s"); values.append(status)
    if not fields:
        return
    col_names = [f.split(" =")[0] for f in fields]
    sql = (
        "INSERT INTO chat_history (conv_uid, chat_mode, summary, "
        + ", ".join(col_names) + ") "
        + "VALUES (%s, 'chat_normal', '', " + ", ".join(["%s"] * len(values)) + ") "
        + "ON DUPLICATE KEY UPDATE " + ", ".join(fields)
    )
    params = [conv_uid] + values + values
    conn = pymysql.connect(**_MYSQL_CONFIG)
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def _get_conv_binding(conv_uid: str) -> dict:
    """读取会话绑定的数据源/知识库/提示词/状态（从 chat_history 表）。
    返回 datasource_id/knowledge_space_id/prompt_code/status + 名称（knowledge_space 通过 JOIN 查）。
    """
    conn = pymysql.connect(**_MYSQL_CONFIG)
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute(
                "SELECT ch.datasource_id, ch.knowledge_space_id, ch.prompt_code, ch.status, "
                "ks.name as knowledge_space_name "
                "FROM chat_history ch "
                "LEFT JOIN knowledge_space ks ON ch.knowledge_space_id = ks.id "
                "WHERE ch.conv_uid = %s",
                (conv_uid,)
            )
            row = cursor.fetchone()
            if not row:
                return {}
            result = {
                "datasource_id": row.get("datasource_id"),
                "knowledge_space_id": row.get("knowledge_space_id"),
                "prompt_code": row.get("prompt_code"),
                "status": row.get("status") or "active",
                "knowledge_space": row.get("knowledge_space_name") or "",
                "database_name": "",
            }
            return result
    finally:
        conn.close()


class NewConversationRequest(BaseModel):
    user_name: Optional[str] = Field(None, description="用户名")
    sys_code: Optional[str] = Field(None, description="系统编码")
    datasource_name: Optional[str] = Field(None, description="绑定的数据源名称")
    knowledge_space_name: Optional[str] = Field(None, description="绑定的知识库名称")
    prompt_code: Optional[str] = Field(None, description="绑定的提示词 code")


class DeleteConversationRequest(BaseModel):
    con_uid: str = Field(..., description="会话 UID")


class ClearConversationRequest(BaseModel):
    user_name: Optional[str] = Field(None, description="用户名")
    sys_code: Optional[str] = Field(None, description="系统编码")


class QueryPageRequest(BaseModel):
    user_name: Optional[str] = Field(None, description="用户名")
    sys_code: Optional[str] = Field(None, description="系统编码")
    page: int = Field(1, description="页码")
    page_size: int = Field(20, description="每页条数")


async def _v1_get(path: str, **params) -> dict:
    """请求 DB-GPT v1 API（GET）。"""
    params = {k: v for k, v in params.items() if v is not None}
    async with httpx.AsyncClient(timeout=30, trust_env=False) as c:
        resp = await c.get(f"{_DIALOGUE_BASE}{path}", params=params)
        if resp.status_code != 200:
            raise HTTPException(resp.status_code, detail=resp.text)
        return resp.json()


async def _v1_post(path: str, body: dict) -> dict:
    """请求 DB-GPT v1 API（POST）。"""
    async with httpx.AsyncClient(timeout=30, trust_env=False) as c:
        resp = await c.post(f"{_DIALOGUE_BASE}{path}", json=body)
        if resp.status_code != 200:
            raise HTTPException(resp.status_code, detail=resp.text)
        return resp.json()


@router.post("/new")
async def new_conversation(req: NewConversationRequest):
    """新建会话。创建后写入绑定的数据源/知识库/提示词。

    API: POST /api/v1/chat/dialogue/new
    """
    try:
        data = await _v1_post("/new", {"user_name": req.user_name, "sys_code": req.sys_code})
        # DB-GPT 返回 {success: True, data: {conv_uid: "xxx"}}
        conv_uid = ""
        if isinstance(data, dict):
            inner = data.get("data", data)
            conv_uid = inner.get("conv_uid", "") if isinstance(inner, dict) else ""
        if conv_uid:
            # 将名称解析为 ID
            ids = _resolve_ids(
                datasource_name=req.datasource_name,
                knowledge_space_name=req.knowledge_space_name,
            )
            if req.datasource_name:
                # 通过 qna_agent 自己的 datasource API 查数据源 ID
                try:
                    async with httpx.AsyncClient(timeout=10, trust_env=False) as hc:
                        ds_resp = await hc.get("http://localhost:8080/datasources")
                        ds_list = ds_resp.json().get("datasources", [])
                        for ds in ds_list:
                            if ds.get("db_name") == req.datasource_name:
                                ids["datasource_id"] = ds.get("id")
                                break
                except Exception:
                    pass
            _update_conv_binding(
                conv_uid,
                datasource_id=ids.get("datasource_id"),
                knowledge_space_id=ids.get("knowledge_space_id"),
                prompt_code=req.prompt_code,
            )
        return {"ok": True, "conversation": data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"新建会话失败: {e}")


@router.get("/list")
async def list_conversations(user_name: Optional[str] = None, sys_code: Optional[str] = None):
    """列出会话。摘要使用第一条问题内容。

    API: GET /api/v1/chat/dialogue/list
    """
    try:
        data = await _v1_get("/list", user_name=user_name, sys_code=sys_code)
        # DB-GPT 返回 {success, data: [...]}，提取 data
        convs = data
        if isinstance(data, dict) and "data" in data:
            convs = data["data"]
        if not isinstance(convs, list):
            convs = []

        # 对每条会话，如果 summary 为空，获取第一条问题作为摘要
        # 同时过滤掉没有消息的空会话
        result = []
        for cv in convs:
            summary = cv.get("summary") or ""
            uid = cv.get("conv_uid") or ""
            has_messages = False
            if uid:
                try:
                    msg_data = await _v1_get("/messages/history", con_uid=uid)
                    msgs = msg_data
                    if isinstance(msg_data, dict) and "data" in msg_data:
                        msgs = msg_data["data"]
                    if isinstance(msgs, list) and len(msgs) > 0:
                        has_messages = True
                        # 如果 summary 为空，用第一条 human 消息作为摘要
                        if not summary:
                            first_human = next((m for m in msgs if m.get("role") == "human"), None)
                            if first_human:
                                summary = (first_human.get("context") or first_human.get("content") or "")[:100]
                except Exception:
                    pass
            # 跳过空会话（无消息）
            if not has_messages:
                continue
            # 读取会话绑定的数据源/知识库
            binding = _get_conv_binding(uid) if uid else {}
            result.append({
                "conv_uid": uid,
                "summary": summary,
                "app_code": cv.get("app_code", ""),
                "user_name": cv.get("user_name", ""),
                "gmt_created": cv.get("gmt_created", ""),
                "database_name": binding.get("database_name", ""),
                "knowledge_space": binding.get("knowledge_space", ""),
                "prompt_code": binding.get("prompt_code", ""),
                "status": binding.get("status", "active"),
            })
        return {"ok": True, "conversations": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"获取会话列表失败: {e}")


@router.get("/{conv_uid}/binding")
async def get_binding(conv_uid: str):
    """获取会话绑定的数据源/知识库/提示词（返回名称而非 ID）。"""
    try:
        binding = _get_conv_binding(conv_uid)
        return {"ok": True, "binding": binding}
    except Exception as e:
        raise HTTPException(502, detail=f"获取会话绑定信息失败: {e}")


class SetStatusRequest(BaseModel):
    conv_uid: str = Field(..., description="会话 UID")
    status: str = Field(..., description="会话状态：active=进行中 / inactive=已结束")


@router.post("/set-status")
async def set_conv_status(req: SetStatusRequest):
    """设置会话状态（active/inactive）。"""
    try:
        _update_conv_binding(req.conv_uid, status=req.status)
        return {"ok": True, "conv_uid": req.conv_uid, "status": req.status}
    except Exception as e:
        raise HTTPException(502, detail=f"设置会话状态失败: {e}")


class SaveBindingRequest(BaseModel):
    conv_uid: str = Field(..., description="会话 UID")
    datasource_name: Optional[str] = Field(None, description="数据源名称")
    knowledge_space_name: Optional[str] = Field(None, description="知识库名称")
    prompt_code: Optional[str] = Field(None, description="提示词 code")


@router.post("/save-binding")
async def save_binding(req: SaveBindingRequest):
    """保存/更新会话的数据源/知识库/提示词绑定。"""
    try:
        ids = _resolve_ids(
            datasource_name=req.datasource_name,
            knowledge_space_name=req.knowledge_space_name,
        )
        # 解析数据源 ID
        if req.datasource_name and "datasource_id" not in ids:
            try:
                async with httpx.AsyncClient(timeout=10, trust_env=False) as hc:
                    ds_resp = await hc.get("http://localhost:8080/datasources")
                    ds_list = ds_resp.json().get("datasources", [])
                    for ds in ds_list:
                        if ds.get("db_name") == req.datasource_name:
                            ids["datasource_id"] = ds.get("id")
                            break
            except Exception:
                pass
        _update_conv_binding(
            req.conv_uid,
            datasource_id=ids.get("datasource_id"),
            knowledge_space_id=ids.get("knowledge_space_id"),
            prompt_code=req.prompt_code,
        )
        return {"ok": True}
    except Exception as e:
        raise HTTPException(502, detail=f"保存绑定失败: {e}")


@router.post("/delete")
async def delete_conversation(req: DeleteConversationRequest):
    """删除会话。

    API: POST /api/v1/chat/dialogue/delete?con_uid=xxx
    DB-GPT 的 delete 接口用 query param 而非 JSON body。
    """
    try:
        async with httpx.AsyncClient(timeout=30, trust_env=False) as c:
            resp = await c.post(f"{_DIALOGUE_BASE}/delete", params={"con_uid": req.con_uid})
            if resp.status_code != 200:
                raise HTTPException(resp.status_code, detail=resp.text)
        return {"ok": True, "deleted": req.con_uid}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"删除会话失败: {e}")


@router.post("/clear")
async def clear_conversations(req: ClearConversationRequest):
    """清空用户所有会话。

    API: POST /api/v1/chat/dialogue/clear
    """
    try:
        data = await _v1_post("/clear", req.model_dump(exclude_none=True))
        return {"ok": True, "cleared": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"清空会话失败: {e}")


@router.get("/messages/history")
async def get_history(con_uid: str):
    """获取会话历史消息。

    API: GET /api/v1/chat/dialogue/messages/history?con_uid=xxx
    """
    try:
        data = await _v1_get("/messages/history", con_uid=con_uid)
        return {"ok": True, "messages": data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"获取历史消息失败: {e}")


@router.post("/query_page")
async def query_page(req: QueryPageRequest):
    """分页查询会话。

    API: POST /api/v1/chat/dialogue/query_page
    """
    try:
        data = await _v1_post("/query_page", req.model_dump(exclude_none=True))
        return {"ok": True, "page": data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"分页查询会话失败: {e}")
