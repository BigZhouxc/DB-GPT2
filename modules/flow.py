# -*- coding: utf-8 -*-
"""AWEL Flow 管理模块 —— 封装 DB-GPT SDK flow 函数。

SDK 直接封装：create / update / delete / get / list
"""
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dbgpt_client.flow import (
    create_flow,
    delete_flow,
    get_flow,
    list_flow,
    update_flow,
)

from core.client_factory import get_client

router = APIRouter(prefix="/flows", tags=["AWEL Flow 管理"])


class FlowCreateRequest(BaseModel):
    """Flow 创建请求（简化版，实际 Flow 结构较复杂）。"""
    name: str = Field(..., description="Flow 名称")
    label: Optional[str] = Field(None, description="标签")
    description: Optional[str] = Field(None, description="描述")
    flow_data: dict = Field(default_factory=dict, description="Flow 图数据")


@router.get("")
@router.get("/")
async def list_flows(name: Optional[str] = None, uid: Optional[str] = None):
    """列出所有 Flow。"""
    try:
        client = get_client()
        result = await list_flow(client, name=name, uid=uid)
        return {
            "ok": True,
            "flows": [
                {
                    "uid": f.uid, "name": f.name, "label": f.label,
                    "version": f.version, "description": f.description,
                    "state": f.state, "editable": f.editable,
                }
                for f in result
            ],
        }
    except Exception as e:
        raise HTTPException(502, detail=f"获取 Flow 列表失败: {e}")


@router.get("/{flow_id}")
async def get_one(flow_id: str):
    """获取指定 Flow 详情。"""
    try:
        client = get_client()
        f = await get_flow(client, flow_id)
        return {
            "ok": True,
            "flow": {
                "uid": f.uid, "name": f.name, "label": f.label,
                "version": f.version, "description": f.description,
                "state": f.state, "editable": f.editable,
            },
        }
    except Exception as e:
        raise HTTPException(502, detail=f"获取 Flow 失败: {e}")


@router.post("")
@router.post("/")
async def create(req: FlowCreateRequest):
    """创建 Flow（实际 flow_data 需要完整的 DAG 结构）。"""
    try:
        client = get_client()
        # 构造 FlowPanel（简化版，实际需要完整 DAG 节点结构）
        from dbgpt.core.awel.flow.flow_factory import FlowPanel
        panel = FlowPanel(**req.flow_data) if req.flow_data else FlowPanel(name=req.name)
        if req.name:
            panel.name = req.name
        if req.label:
            panel.label = req.label
        if req.description:
            panel.description = req.description
        result = await create_flow(client, panel)
        return {
            "ok": True,
            "flow": {
                "uid": result.uid, "name": result.name,
                "label": result.label, "description": result.description,
            },
        }
    except Exception as e:
        raise HTTPException(502, detail=f"创建 Flow 失败: {e}")


@router.put("/{flow_uid}")
async def update(flow_uid: str, req: FlowCreateRequest):
    """更新 Flow。"""
    try:
        client = get_client()
        from dbgpt.core.awel.flow.flow_factory import FlowPanel
        panel = FlowPanel(**req.flow_data) if req.flow_data else FlowPanel()
        panel.uid = flow_uid
        if req.name:
            panel.name = req.name
        if req.label:
            panel.label = req.label
        if req.description:
            panel.description = req.description
        result = await update_flow(client, panel)
        return {
            "ok": True,
            "flow": {
                "uid": result.uid, "name": result.name,
                "label": result.label, "description": result.description,
            },
        }
    except Exception as e:
        raise HTTPException(502, detail=f"更新 Flow 失败: {e}")


@router.delete("/{flow_id}")
async def delete_one(flow_id: str):
    """删除 Flow。"""
    try:
        client = get_client()
        result = await delete_flow(client, flow_id)
        return {
            "ok": True,
            "flow": {"uid": result.uid, "name": result.name},
        }
    except Exception as e:
        raise HTTPException(502, detail=f"删除 Flow 失败: {e}")
