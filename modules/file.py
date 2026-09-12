# -*- coding: utf-8 -*-
"""会话附件文件模块 —— 代理 DB-GPT 的 session_file 上传接口。

DB-GPT 前端在 react-agent 中通过 ext_info.file_ids 挂载已上传的本地文件。
上传路由挂载在 DB-GPT 的 /api/v1/agent/files（SessionFileServe）。

对外：
  POST   /files/upload           上传 1..N 个文件到当前会话，返回 file_id 列表
  GET    /files                  列出当前会话已上传的文件
  DELETE /files/{file_id}        删除指定会话文件

前端流程：先在会话中上传文件拿到 file_ids，再在 react-agent 请求里带上
file_ids，DB-GPT 会把文件内容纳入 Agent 上下文。
"""
import os

import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from typing import Optional

router = APIRouter(prefix="/files", tags=["会话附件"])

DBGPT_API_BASE = os.getenv("DBGPT_API_BASE", "http://127.0.0.1:5670/api/v2")
# SessionFileServe 挂载在 v1 路径
_FILES_BASE = DBGPT_API_BASE.replace("/api/v2", "/api/v1") + "/agent/files"


def _httpx() -> "httpx.AsyncClient":
    """返回绕过代理的 AsyncClient（与 client_factory 一致）。"""
    return httpx.AsyncClient(timeout=float(os.getenv("TIMEOUT", "300")), trust_env=False)


@router.post("/upload")
async def upload_files(
    files: list[UploadFile] = File(...),
    session_id: Optional[str] = Form(None),
):
    """上传文件到指定会话。

    代理 DB-GPT POST /api/v1/agent/files（multipart/form-data）。
    返回每个文件的 file_id / name / size，供 react-agent ext_info.file_ids 使用。

    Args:
        files: 待上传文件（1..N）
        session_id: 会话 ID（推荐传 State.currentSessionId，缺省也可）
    """
    try:
        async with _httpx() as c:
            # httpx multipart：files 列表 + data 表单
            data = {"session_id": session_id} if session_id else {}
            files_payload = []
            for f in files:
                content = await f.read()
                files_payload.append(
                    (f"files", (f.filename or "file", content, f.content_type or "application/octet-stream"))
                )
            resp = await c.post(_FILES_BASE, data=data, files=files_payload)
            body = resp.json()
            if resp.status_code != 200 or not body.get("success"):
                raise HTTPException(resp.status_code, detail=f"DB-GPT: {body.get('err_msg') or body}")
            raw = body.get("data") or []
            files_out = []
            for item in raw:
                files_out.append(
                    {
                        "file_id": item.get("file_id") or item.get("id"),
                        "name": item.get("name") or item.get("display_name") or "",
                        "size": item.get("size") or item.get("size_bytes") or 0,
                        "media_type": item.get("media_type") or "",
                        "status": item.get("status") or "ready",
                    }
                )
            return {"ok": True, "files": files_out, "session_id": session_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, detail=f"文件上传失败: {e}")


@router.get("")
async def list_files(session_id: Optional[str] = None):
    """列出当前会话已上传的文件。"""
    try:
        params = {"session_id": session_id} if session_id else {}
        async with _httpx() as c:
            resp = await c.get(_FILES_BASE, params=params)
            body = resp.json()
            if resp.status_code != 200 or not body.get("success"):
                raise HTTPException(resp.status_code, detail=f"DB-GPT: {body.get('err_msg') or body}")
            raw = body.get("data") or []
            files_out = [
                {
                    "file_id": item.get("file_id") or item.get("id"),
                    "name": item.get("name") or item.get("display_name") or "",
                    "size": item.get("size") or item.get("size_bytes") or 0,
                    "media_type": item.get("media_type") or "",
                    "status": item.get("status") or "ready",
                }
                for item in raw
            ]
            return {"ok": True, "files": files_out}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, detail=f"获取文件列表失败: {e}")


@router.delete("/{file_id}")
async def delete_file(file_id: str, session_id: Optional[str] = None):
    """删除指定会话文件。"""
    try:
        params = {"session_id": session_id} if session_id else {}
        async with _httpx() as c:
            resp = await c.delete(f"{_FILES_BASE}/{file_id}", params=params)
            body = resp.json()
            if resp.status_code != 200 or not body.get("success"):
                raise HTTPException(resp.status_code, detail=f"DB-GPT: {body.get('err_msg') or body}")
            return {"ok": True, "deleted": file_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, detail=f"删除文件失败: {e}")
