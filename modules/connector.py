# -*- coding: utf-8 -*-
"""MCP 连接器管理模块 —— 全部走 Serve 通用 HTTP 路由。

serve 路由前缀: /connectors
"""
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.client_factory import get_client

router = APIRouter(prefix="/connectors", tags=["MCP 连接器"])


# ---------------------------------------------------------------------------
# Pydantic 请求模型
# ---------------------------------------------------------------------------
class ConnectorCreateRequest(BaseModel):
    type: str = Field(..., description="连接器类型，如 custom_mcp")
    name: str = Field(..., description="连接器名称")
    config: dict = Field(default_factory=dict, description="配置参数")
    user_name: Optional[str] = Field(None, description="用户名")
    sys_code: Optional[str] = Field(None, description="系统编码")


class ConnectorUpdateRequest(BaseModel):
    type: Optional[str] = None
    name: Optional[str] = None
    config: Optional[dict] = None
    user_name: Optional[str] = None
    sys_code: Optional[str] = None


class ConfirmRequest(BaseModel):
    confirm_id: str = Field(..., description="确认 ID")
    approved: bool = Field(..., description="是否批准")
    reason: Optional[str] = Field(None, description="理由")


# ---------------------------------------------------------------------------
# 接口
# ---------------------------------------------------------------------------
@router.get("/types")
async def list_types():
    """列出所有连接器类型。

    serve: GET /connectors/types
    """
    try:
        client = get_client()
        res = await client.get("/connectors/types")
        data = res.json()
        if data.get("success"):
            return {"ok": True, "types": data["data"]}
        raise HTTPException(502, detail=str(data))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"获取连接器类型失败: {e}")


@router.get("")
@router.get("/")
async def list_connectors(user_name: Optional[str] = None, sys_code: Optional[str] = None):
    """列出所有连接器。

    serve: GET /connectors/
    """
    try:
        client = get_client()
        params = {}
        if user_name:
            params["user_name"] = user_name
        if sys_code:
            params["sys_code"] = sys_code
        res = await client.get("/connectors/", **params)
        data = res.json()
        if data.get("success"):
            return {"ok": True, "connectors": data["data"]}
        raise HTTPException(502, detail=str(data))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"获取连接器列表失败: {e}")


@router.get("/{connector_id}")
async def get_one(connector_id: str):
    """获取指定连接器详情。

    serve: GET /connectors/{connector_id}
    """
    try:
        client = get_client()
        res = await client.get(f"/connectors/{connector_id}")
        data = res.json()
        if data.get("success"):
            return {"ok": True, "connector": data["data"]}
        raise HTTPException(404, detail=str(data))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"获取连接器失败: {e}")


@router.post("")
@router.post("/")
async def create(req: ConnectorCreateRequest):
    """创建连接器。

    serve: POST /connectors/
    """
    try:
        client = get_client()
        res = await client.post("/connectors/", req.model_dump(exclude_none=True))
        data = res.json()
        if data.get("success"):
            return {"ok": True, "connector": data["data"]}
        raise HTTPException(400, detail=str(data))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"创建连接器失败: {e}")


@router.put("/{connector_id}")
async def update(connector_id: str, req: ConnectorUpdateRequest):
    """更新连接器。

    serve: PUT /connectors/{connector_id}
    """
    try:
        client = get_client()
        body = req.model_dump(exclude_none=True)
        res = await client.put(f"/connectors/{connector_id}", body)
        data = res.json()
        if data.get("success"):
            return {"ok": True, "connector": data["data"]}
        raise HTTPException(400, detail=str(data))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"更新连接器失败: {e}")


@router.delete("/{connector_id}")
async def delete_one(connector_id: str):
    """删除连接器。

    serve: DELETE /connectors/{connector_id}
    """
    try:
        client = get_client()
        res = await client.delete(f"/connectors/{connector_id}")
        data = res.json()
        if data.get("success"):
            return {"ok": True, "deleted": True}
        raise HTTPException(400, detail=str(data))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"删除连接器失败: {e}")


@router.post("/{connector_id}/test")
async def test_one(connector_id: str):
    """测试连接器连通性。

    serve: POST /connectors/{connector_id}/test
    """
    try:
        client = get_client()
        res = await client.post(f"/connectors/{connector_id}/test", {})
        data = res.json()
        if data.get("success"):
            return {"ok": True, "result": data["data"]}
        raise HTTPException(400, detail=str(data))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"测试连接器失败: {e}")


@router.get("/{connector_id}/tools")
async def get_tools(connector_id: str):
    """获取连接器提供的工具列表。

    serve: GET /connectors/{connector_id}/tools
    """
    try:
        client = get_client()
        res = await client.get(f"/connectors/{connector_id}/tools")
        data = res.json()
        if data.get("success"):
            return {"ok": True, "tools": data["data"]}
        raise HTTPException(404, detail=str(data))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"获取工具列表失败: {e}")


@router.get("/pending-confirms")
async def list_pending_confirms():
    """列出待确认的操作。

    serve: GET /connectors/pending-confirms
    """
    try:
        client = get_client()
        res = await client.get("/connectors/pending-confirms")
        return {"ok": True, "confirms": res.json()}
    except Exception as e:
        raise HTTPException(502, detail=f"获取待确认列表失败: {e}")


@router.post("/confirm")
async def confirm_action(req: ConfirmRequest):
    """确认/拒绝待确认操作。

    serve: POST /connectors/confirm
    """
    try:
        client = get_client()
        res = await client.post("/connectors/confirm", req.model_dump(exclude_none=True))
        data = res.json()
        return {"ok": True, "result": data}
    except Exception as e:
        raise HTTPException(502, detail=f"确认操作失败: {e}")
