# -*- coding: utf-8 -*-
"""知识库管理模块 —— 封装 DB-GPT SDK knowledge 函数 + serve 通用 HTTP 路由。

SDK 直接封装：空间 CRUD、文档 CRUD、文档同步
Serve 通用 HTTP：知识库检索
"""
import os
from typing import Optional

import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from dbgpt_client.knowledge import (
    create_document,
    create_space,
    delete_document,
    delete_space,
    get_document,
    get_space,
    list_document,
    list_space,
    sync_document,
    update_space,
)
from dbgpt_client.schema import DocumentModel, SpaceModel, SyncModel

from core.client_factory import get_client

router = APIRouter(prefix="/knowledge", tags=["知识库管理"])


# ---------------------------------------------------------------------------
# Pydantic 请求模型
# ---------------------------------------------------------------------------
class SpaceCreateRequest(BaseModel):
    name: str = Field(..., description="知识空间名称")
    vector_type: str = Field("", description="向量类型")
    desc: str = Field("", description="描述")
    owner: str = Field("", description="所有者")
    context: Optional[str] = Field(None, description="空间参数上下文")


class SpaceUpdateRequest(BaseModel):
    id: int = Field(..., description="空间 ID")
    name: str = Field("", description="名称")
    vector_type: str = Field("", description="向量类型")
    desc: str = Field("", description="描述")
    owner: str = Field("", description="所有者")
    context: Optional[str] = Field(None, description="上下文")


class DocCreateRequest(BaseModel):
    doc_name: str = Field(..., description="文档名称")
    doc_type: str = Field("document", description="文档类型")
    content: str = Field("", description="文档内容")
    doc_source: str = Field("", description="文档来源")
    space_id: str = Field("", description="空间 ID")


class SyncRequest(BaseModel):
    doc_id: str = Field(..., description="文档 ID")
    space_id: str = Field("", description="空间 ID")
    model_name: Optional[str] = Field(None, description="模型名称")


class RetrieveRequest(BaseModel):
    query: str = Field(..., description="检索问题")
    top_k: int = Field(5, description="返回 Top K")
    score_threshold: float = Field(0.3, description="相似度阈值")


# ---------------------------------------------------------------------------
# 知识空间 CRUD（SDK 封装）
# ---------------------------------------------------------------------------
@router.get("/spaces")
@router.get("/spaces/")
async def list_spaces():
    """列出所有知识空间。

    SDK 的 list_space 用 SpaceModel 解析，但 serve 返回的 owner 字段可能为 None，
    导致 pydantic validation error。改用通用 HTTP 调用。
    """
    try:
        client = get_client()
        res = await client.get("/knowledge/spaces")
        data = res.json()
        if not data.get("success"):
            raise HTTPException(502, detail=str(data))
        # serve 返回分页结构: {items: [...], total_count, page, page_size}
        raw_data = data["data"]
        if isinstance(raw_data, dict) and "items" in raw_data:
            items = raw_data["items"]
        elif isinstance(raw_data, list):
            items = raw_data
        else:
            items = []
        return {
            "ok": True,
            "spaces": [
                {"id": s.get("id"), "name": s.get("name", ""),
                 "vector_type": s.get("vector_type", ""),
                 "desc": s.get("desc", ""), "owner": s.get("owner") or "",
                 "context": s.get("context")}
                for s in items
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"获取知识空间列表失败: {e}")


@router.get("/spaces/{space_id}")
async def get_one_space(space_id: str):
    """获取指定知识空间详情。

    同样用通用 HTTP 调用避免 SDK 的 SpaceModel 字段验证问题。
    """
    try:
        client = get_client()
        res = await client.get(f"/knowledge/spaces/{space_id}")
        data = res.json()
        if not data.get("success"):
            raise HTTPException(404, detail=str(data))
        raw = data["data"]
        # serve 返回的 data 可能是 [[key, value], ...] 格式或 dict
        if isinstance(raw, list) and raw and isinstance(raw[0], list):
            s = dict(raw)
        elif isinstance(raw, dict):
            s = raw
        else:
            s = {}
        return {
            "ok": True,
            "space": {
                "id": s.get("id"), "name": s.get("name", ""),
                "vector_type": s.get("vector_type", ""),
                "desc": s.get("desc", ""), "owner": s.get("owner") or "",
                "context": s.get("context"),
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"获取知识空间失败: {e}")


@router.post("/spaces")
@router.post("/spaces/")
async def create_space_endpoint(req: SpaceCreateRequest):
    """创建知识空间。"""
    try:
        client = get_client()
        sm = SpaceModel(**req.model_dump())
        result = await create_space(client, sm)
        return {
            "ok": True,
            "space": {
                "id": result.id, "name": result.name,
                "vector_type": result.vector_type, "desc": result.desc,
            },
        }
    except Exception as e:
        raise HTTPException(502, detail=f"创建知识空间失败: {e}")


@router.put("/spaces")
@router.put("/spaces/")
async def update_space_endpoint(req: SpaceUpdateRequest):
    """更新知识空间。"""
    try:
        client = get_client()
        sm = SpaceModel(**req.model_dump())
        result = await update_space(client, sm)
        return {
            "ok": True,
            "space": {
                "id": result.id, "name": result.name,
                "desc": result.desc,
            },
        }
    except Exception as e:
        raise HTTPException(502, detail=f"更新知识空间失败: {e}")


@router.delete("/spaces/{space_id}")
async def delete_space_endpoint(space_id: str):
    """删除知识空间。"""
    try:
        client = get_client()
        result = await delete_space(client, space_id)
        return {
            "ok": True,
            "space": {"id": result.id, "name": result.name},
        }
    except Exception as e:
        raise HTTPException(502, detail=f"删除知识空间失败: {e}")


# ---------------------------------------------------------------------------
# 文档 CRUD（SDK 封装）
# ---------------------------------------------------------------------------
@router.get("/documents")
@router.get("/documents/")
async def list_documents():
    """列出所有文档。

    改用通用 HTTP 调用避免 SDK 的 DocumentModel 字段验证问题。
    """
    try:
        client = get_client()
        res = await client.get("/knowledge/documents")
        data = res.json()
        if not data.get("success"):
            raise HTTPException(502, detail=str(data))
        # serve 返回分页结构: {items: [...], total_count, page, page_size}
        raw_data = data["data"]
        if isinstance(raw_data, dict) and "items" in raw_data:
            items = raw_data["items"]
        elif isinstance(raw_data, list):
            items = raw_data
        else:
            items = []
        return {
            "ok": True,
            "documents": [
                {"id": d.get("id"), "doc_name": d.get("name") or d.get("doc_name") or "",
                 "doc_type": d.get("doc_type", ""),
                 "content": (d.get("content") or "")[:200],
                 "doc_source": d.get("doc_source", ""),
                 "space_id": d.get("space_id")}
                for d in items
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"获取文档列表失败: {e}")


@router.get("/documents/{document_id}")
async def get_one_document(document_id: str):
    """获取指定文档详情。

    改用通用 HTTP 调用。
    """
    try:
        client = get_client()
        res = await client.get(f"/knowledge/documents/{document_id}")
        data = res.json()
        if not data.get("success"):
            raise HTTPException(404, detail=str(data))
        d = data["data"]
        return {
            "ok": True,
            "document": {
                "id": d.get("id"), "doc_name": d.get("doc_name", ""),
                "doc_type": d.get("doc_type", ""),
                "content": d.get("content", ""),
                "doc_source": d.get("doc_source", ""),
                "space_id": d.get("space_id"),
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"获取文档失败: {e}")


@router.post("/documents")
@router.post("/documents/")
async def create_document_endpoint(req: DocCreateRequest):
    """新建文档。"""
    try:
        client = get_client()
        dm = DocumentModel(**req.model_dump())
        result = await create_document(client, dm)
        return {
            "ok": True,
            "document": {
                "id": result.id, "doc_name": result.doc_name,
                "doc_type": result.doc_type,
            },
        }
    except Exception as e:
        raise HTTPException(502, detail=f"创建文档失败: {e}")


@router.delete("/documents/{document_id}")
async def delete_document_endpoint(document_id: str):
    """删除文档。"""
    try:
        client = get_client()
        result = await delete_document(client, document_id)
        return {
            "ok": True,
            "document": {"id": result.id, "doc_name": result.doc_name},
        }
    except Exception as e:
        raise HTTPException(502, detail=f"删除文档失败: {e}")


# ---------------------------------------------------------------------------
# 文档同步（SDK 封装）
# ---------------------------------------------------------------------------
@router.post("/documents/sync")
@router.post("/documents/sync/")
async def sync_documents_endpoint(req: SyncRequest):
    """同步文档到知识库。"""
    try:
        client = get_client()
        sm = SyncModel(**req.model_dump())
        result = await sync_document(client, sm)
        return {"ok": True, "synced_doc_ids": result}
    except Exception as e:
        raise HTTPException(502, detail=f"同步文档失败: {e}")


# ---------------------------------------------------------------------------
# 知识库检索（Serve 通用 HTTP）
# ---------------------------------------------------------------------------
@router.post("/spaces/{space_id}/retrieve")
async def retrieve(space_id: int, req: RetrieveRequest):
    """知识库检索。

    serve 路由: POST /spaces/{space_id}/retrieve
    """
    try:
        client = get_client()
        body = {
            "query": req.query,
            "top_k": req.top_k,
            "score_threshold": req.score_threshold,
        }
        res = await client.post(f"/knowledge/spaces/{space_id}/retrieve", body)
        data = res.json()
        if data.get("success"):
            return {"ok": True, "results": data["data"]}
        raise HTTPException(400, detail=str(data))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"知识库检索失败: {e}")


# ---------------------------------------------------------------------------
# 文档上传（multipart —— 支持本地文件直接入知识库）
# ---------------------------------------------------------------------------
@router.post("/documents/upload")
async def upload_document(
    space_id: str = Form(...),
    doc_name: str = Form(None),
    doc_type: str = Form("txt"),
    content: Optional[str] = Form(None),
    doc_file: UploadFile = File(None),
    chunk_strategy: str = Form("Automatic"),
    chunk_size: int = Form(512),
    chunk_overlap: int = Form(50),
    separator: str = Form("\n"),
    model_name: Optional[str] = Form(None),
    auto_sync: bool = Form(True),
):
    """上传本地文件到知识库空间（multipart/form-data），支持分块参数。

    代理 DB-GPT POST /api/v2/serve/knowledge/documents 创建文档，
    随后（auto_sync=True 时）自动调用 POST /api/v2/serve/knowledge/documents/sync
    触发文档同步（向量化），与 DB-GPT 前端"上传+同步"一步到位的体验一致。

    Args:
        space_id: 知识空间 ID 或名称
        doc_name: 文档名（缺省取文件名）
        doc_type: 文档类型（txt / markdown / pdf / csv / document）
        content: 纯文本内容（与 doc_file 二选一）
        doc_file: 本地文件（与 content 二选一）
        chunk_strategy: 分块策略（Automatic / CHUNK_BY_SIZE / CHUNK_BY_PAGE /
                        CHUNK_BY_PARAGRAPH / CHUNK_BY_SEPARATOR / CHUNK_BY_MARKDOWN_HEADER）
        chunk_size: 分块大小（默认 512）
        chunk_overlap: 分块重叠（默认 50）
        separator: 分隔符（默认 \\n）
        model_name: 用于摘要的模型名（可选）
        auto_sync: 是否上传后自动同步（默认 True）
    """
    import os

    base = os.getenv("DBGPT_API_BASE", "http://127.0.0.1:5670/api/v2")
    url = base + "/serve/knowledge/documents"
    sync_url = base + "/serve/knowledge/documents/sync"
    name = doc_name or (doc_file.filename if doc_file else "document")

    data = {
        "space_id": space_id,
        "doc_name": name,
        "doc_type": doc_type,
    }
    files = []
    if doc_file:
        raw = await doc_file.read()
        files.append(("doc_file", (doc_file.filename or name, raw, doc_file.content_type or "application/octet-stream")))
    if content:
        data["content"] = content

    try:
        async with httpx.AsyncClient(timeout=float(os.getenv("TIMEOUT", "300")), trust_env=False) as c:
            # 第一步：创建文档
            resp = await c.post(url, data=data, files=files or None)
            body = resp.json()
            if resp.status_code != 200 or not body.get("success"):
                raise HTTPException(502, detail=f"DB-GPT: {body.get('err_msg') or body}")
            d = body.get("data") or {}
            doc_id = d.get("id")
            doc_name_resolved = d.get("doc_name") or d.get("name") or name

            sync_status = "skipped"
            sync_result = None

            # 第二步：自动同步（向量化）
            if auto_sync and doc_id:
                sync_body = [{
                    "doc_id": doc_id,
                    "space_id": str(space_id),
                    "model_name": model_name or os.getenv("MODEL", ""),
                    "chunk_parameters": {
                        "chunk_strategy": chunk_strategy,
                        "chunk_size": chunk_size,
                        "chunk_overlap": chunk_overlap,
                        "separator": separator,
                    },
                }]
                try:
                    sync_resp = await c.post(sync_url, json=sync_body)
                    sync_body_resp = sync_resp.json()
                    if sync_resp.status_code == 200 and sync_body_resp.get("success"):
                        sync_status = "syncing"
                        sync_result = sync_body_resp.get("data")
                    else:
                        sync_status = f"failed: {sync_body_resp.get('err_msg', '')[:100]}"
                except Exception as se:
                    sync_status = f"failed: {str(se)[:100]}"

            return {
                "ok": True,
                "document": {
                    "id": doc_id,
                    "doc_name": doc_name_resolved,
                    "doc_type": d.get("doc_type") or doc_type,
                    "space_id": d.get("space_id") or space_id,
                },
                "sync_status": sync_status,
                "sync_result": sync_result,
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"文档上传失败: {e}")
