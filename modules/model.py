# -*- coding: utf-8 -*-
"""模型管理模块 —— 全部走 Serve 通用 HTTP 路由。

serve 路由前缀: /models
"""
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.client_factory import get_client

router = APIRouter(prefix="/models", tags=["模型管理"])


class ModelStartRequest(BaseModel):
    model_name: str = Field(..., description="模型名称")
    model_type: str = Field(..., description="模型类型")
    host: Optional[str] = Field(None, description="主机")
    port: Optional[int] = Field(None, description="端口")
    worker_type: Optional[str] = Field(None, description="Worker 类型")
    params: Optional[dict] = Field(None, description="额外参数")


@router.get("/model-types")
async def list_model_types():
    """列出支持的模型类型。

    serve: GET /models/model-types
    """
    try:
        client = get_client()
        res = await client.get("/model/model-types")
        data = res.json()
        if data.get("success"):
            return {"ok": True, "model_types": data["data"]}
        raise HTTPException(502, detail=str(data))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"获取模型类型失败: {e}")


@router.get("/list")
@router.get("/")
async def list_models():
    """列出所有运行中的模型。

    serve: GET /model/models
    """
    try:
        client = get_client()
        res = await client.get("/model/models")
        data = res.json()
        if data.get("success"):
            return {"ok": True, "models": data["data"]}
        raise HTTPException(502, detail=str(data))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"获取模型列表失败: {e}")


@router.post("/start")
async def start_model(req: ModelStartRequest):
    """启动模型。

    serve: POST /models/models/start
    """
    try:
        client = get_client()
        res = await client.post("/model/models/start", req.model_dump(exclude_none=True))
        data = res.json()
        if data.get("success"):
            return {"ok": True, "result": data["data"]}
        raise HTTPException(400, detail=str(data))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"启动模型失败: {e}")


@router.post("/stop")
async def stop_model(req: ModelStartRequest):
    """停止模型。

    serve: POST /models/models/stop
    """
    try:
        client = get_client()
        res = await client.post("/model/models/stop", req.model_dump(exclude_none=True))
        data = res.json()
        if data.get("success"):
            return {"ok": True, "result": data["data"]}
        raise HTTPException(400, detail=str(data))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"停止模型失败: {e}")
