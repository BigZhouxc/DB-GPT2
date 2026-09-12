# -*- coding: utf-8 -*-
"""Prompt 管理模块 —— 使用 DB-GPT v1 API（非 serve 路由）。

DB-GPT 的 Prompt 管理在 /prompt/ 路径下，不在 serve 路由下。
所以用 httpx 直接请求 v1 路径。
"""
import os
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/prompts", tags=["Prompt 管理"])

# DB-GPT v1 API 基础路径
DBGPT_BASE = os.getenv("DBGPT_API_BASE", "http://127.0.0.1:5670/api/v2")
_PROMPT_BASE = DBGPT_BASE.replace("/api/v2", "") + "/prompt"


class PromptCreateRequest(BaseModel):
    prompt_name: str = Field(..., description="Prompt 名称")
    content: str = Field(..., description="Prompt 内容")
    prompt_type: str = Field("common", description="Prompt 类型（固定 common）")
    user_name: Optional[str] = Field(None, description="用户名")
    sys_code: Optional[str] = Field(None, description="系统编码")


class PromptUpdateRequest(BaseModel):
    prompt_name: str = Field(..., description="Prompt 名称")
    content: Optional[str] = None
    prompt_type: Optional[str] = None
    scene: Optional[str] = None
    sub_scene: Optional[str] = None
    user_name: Optional[str] = None
    sys_code: Optional[str] = None


class PromptListRequest(BaseModel):
    user_name: Optional[str] = None
    sys_code: Optional[str] = None
    page: int = 1
    page_size: int = 20


async def _post(path: str, body: dict, **params) -> dict:
    """请求 DB-GPT prompt API（POST）。"""
    params = {k: v for k, v in params.items() if v}
    async with httpx.AsyncClient(timeout=30, trust_env=False) as c:
        resp = await c.post(f"{_PROMPT_BASE}{path}", json=body, params=params)
        if resp.status_code != 200:
            raise HTTPException(resp.status_code, detail=resp.text)
        return resp.json()


async def _get(path: str, **params) -> dict:
    """请求 DB-GPT prompt API（GET）。"""
    params = {k: v for k, v in params.items() if v}
    async with httpx.AsyncClient(timeout=30, trust_env=False) as c:
        resp = await c.get(f"{_PROMPT_BASE}{path}", params=params)
        if resp.status_code != 200:
            raise HTTPException(resp.status_code, detail=resp.text)
        return resp.json()


@router.post("/add")
async def create_prompt(req: PromptCreateRequest):
    """创建 Prompt。

    API: POST /prompt/add
    """
    try:
        data = await _post("/add", req.model_dump(exclude_none=True))
        return {"ok": data.get("success", True), "prompt": data.get("data", data)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"创建 Prompt 失败: {e}")


@router.post("/update")
async def update_prompt(req: PromptUpdateRequest):
    """更新 Prompt。

    API: POST /prompt/update
    """
    try:
        data = await _post("/update", req.model_dump(exclude_none=True))
        return {"ok": data.get("success", True), "prompt": data.get("data", data)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"更新 Prompt 失败: {e}")


@router.post("/delete")
async def delete_prompt(prompt_name: str = "", user_name: str = "", sys_code: str = ""):
    """删除 Prompt。

    API: POST /prompt/delete?prompt_name=xxx
    """
    try:
        data = await _post("/delete", {}, prompt_name=prompt_name,
                           user_name=user_name, sys_code=sys_code)
        return {"ok": data.get("success", True), "deleted": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"删除 Prompt 失败: {e}")


@router.post("/list")
async def list_prompts(req: PromptListRequest):
    """列出 Prompt。

    API: POST /prompt/list
    """
    try:
        data = await _post("/list", req.model_dump(exclude_none=True))
        return {"ok": data.get("success", True), "prompts": data.get("data", data)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"获取 Prompt 列表失败: {e}")


@router.get("/type/targets")
async def get_prompt_targets():
    """获取 Prompt 类型目标列表。

    API: GET /prompt/type/targets
    """
    try:
        data = await _get("/type/targets")
        return {"ok": data.get("success", True), "targets": data.get("data", data)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"获取 Prompt 类型目标失败: {e}")
