# -*- coding: utf-8 -*-
"""模型管理模块 —— 全部走 Serve 通用 HTTP 路由。

serve 路由前缀: /models
"""
import re
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.client_factory import get_client

router = APIRouter(prefix="/models", tags=["模型管理"])


def normalize_api_base(api_base: str) -> str:
    """规范化 API 地址 —— 容忍用户粘贴完整 endpoint 或带尾部斜杠。

    规则：
    - 去掉尾部斜杠和空白
    - 若以 /chat/completions 结尾 → 去掉该后缀（DB-GPT/openai client 会自己拼）
    - 结果形如 https://xxx/v1
    """
    if not api_base:
        return api_base
    base = api_base.strip().rstrip("/")
    # 完整 endpoint 或其变体 → 截到 /v1
    base = re.sub(r"/chat/completions$", "", base, flags=re.IGNORECASE)
    return base


class ModelStartRequest(BaseModel):
    model_name: str = Field(..., description="模型名称")
    model_type: str = Field(..., description="模型类型")
    host: Optional[str] = Field(None, description="主机")
    port: Optional[int] = Field(None, description="端口")
    worker_type: Optional[str] = Field(None, description="Worker 类型")
    params: Optional[dict] = Field(None, description="额外参数")
    # 添加模型时的可选配置
    provider: Optional[str] = Field(None, description="模型提供者，如 proxy/openai")
    api_base: Optional[str] = Field(None, description="API 地址")
    api_key: Optional[str] = Field(None, description="API Key")


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
    """启动/添加模型。

    使用 DB-GPT serve API: POST /model/models (create model)
    需要 params 中包含 name, provider 等必填字段。

    鲁棒性：
    - api_base 自动规范化（容忍粘贴完整 endpoint）
    - 实例已存在时自动等待重试（stop→create 竞态）
    """
    import asyncio

    client = get_client()
    wt = req.worker_type or req.model_type

    # 构造 params —— DB-GPT 内部会用 ConfigurationManager 解析
    # LLMDeployModelParameters 必填: name, provider
    # EmbeddingDeployModelParameters 必填: name, provider
    params = dict(req.params or {})
    params.setdefault("name", req.model_name)
    params.setdefault("provider", req.provider or "proxy/openai")
    if req.api_base:
        params.setdefault("api_base", normalize_api_base(req.api_base))
    if req.api_key:
        params.setdefault("api_key", req.api_key)

    serve_body = {
        "model": req.model_name,
        "worker_type": wt,
        "host": req.host or "127.0.0.1",
        "port": req.port or 5670,
        "params": params,
    }
    # 使用 POST /model/models (create) 而非 /model/models/start (start existing)
    # 实例已存在（如同名模型停止中）→ 等 2s 重试，最多 5 次
    last_err = ""
    for attempt in range(5):
        try:
            res = await client.post("/model/models", serve_body)
            data = res.json()
            if data.get("success"):
                return {"ok": True, "result": data["data"]}
            last_err = str(data.get("err_msg", data))
        except HTTPException:
            raise
        except Exception as e:
            last_err = str(e)
        if "instances is exist" not in last_err:
            break
        await asyncio.sleep(2)
    raise HTTPException(400, detail=last_err or "启动模型失败：未知错误")


@router.post("/stop")
async def stop_model(req: ModelStartRequest):
    """停止模型。

    serve: POST /models/models/stop
    DB-GPT serve API 需要字段: model, worker_type, host, port, params
    """
    try:
        client = get_client()
        serve_body = {
            "model": req.model_name,
            "worker_type": req.worker_type or req.model_type,
            "host": req.host or "127.0.0.1",
            "port": req.port or 5670,
            "params": req.params or {},
        }
        res = await client.post("/model/models/stop", serve_body)
        data = res.json()
        if data.get("success"):
            return {"ok": True, "result": data["data"]}
        raise HTTPException(400, detail=str(data.get("err_msg", data)))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"停止模型失败: {e}")


class ModelDeleteRequest(BaseModel):
    model_name: str = Field(..., description="模型名称")
    worker_type: str = Field("llm", description="Worker 类型")
    host: str = Field("127.0.0.1", description="主机")
    port: int = Field(5670, description="端口")
    model: Optional[str] = Field(None, description="模型标识（默认同 model_name）")
    params: Optional[dict] = Field(None, description="额外参数")


@router.delete("/delete")
async def delete_model(req: ModelDeleteRequest):
    """删除模型 — 停止运行实例 + 从 DB 删除记录。

    DB-GPT API: DELETE /api/v1/worker/models
    """
    import os
    import httpx

    api_base = os.getenv("DBGPT_API_BASE", "http://127.0.0.1:5670/api/v2")
    # 把 /api/v2 替换为 /api/v1
    base_v1 = api_base.replace("/api/v2", "/api/v1").replace("/api/v1", "/api/v1")
    # 提取到 host:port 为止
    base_url = base_v1.rsplit("/api", 1)[0]

    body = {
        "model_name": req.model_name,
        "model": req.model or req.model_name,
        "worker_type": req.worker_type,
        "host": req.host,
        "port": req.port,
        "params": req.params or {},
    }
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=30) as http:
            res = await http.request("DELETE", f"{base_url}/api/v1/worker/models", json=body)
            data = res.json()
            if data.get("success"):
                return {"ok": True, "result": data.get("data", True)}
            raise HTTPException(400, detail=str(data.get("err_msg", data)))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"删除模型失败: {e}")


class ModelEditRequest(BaseModel):
    model_name: str = Field(..., description="模型名称")
    model_type: str = Field("llm", description="模型类型")
    worker_type: str = Field("llm", description="Worker 类型")
    host: str = Field("127.0.0.1", description="主机")
    port: int = Field(5670, description="端口")
    model: Optional[str] = Field(None, description="模型标识（默认同 model_name）")
    params: Optional[dict] = Field(None, description="额外参数")
    provider: Optional[str] = Field(None, description="模型提供者")
    api_base: Optional[str] = Field(None, description="API 地址")
    api_key: Optional[str] = Field(None, description="API Key")


@router.put("/edit")
async def edit_model(req: ModelEditRequest):
    """编辑/更新模型配置 — 停止旧实例 → 用新配置重新创建（启动 + 写 DB）。

    不直接调 DB-GPT 的 PUT /worker/models，因为该接口第一步就查
    dbgpt_serve_model 表，而 TOML 配置启动的模型不在 DB 中（表为空），
    会报 "model not found"。这里用 stop + create 组合实现编辑语义：
    - stop：移除内存中的旧实例
    - create：用新配置启动实例，成功后自动写入 DB
    这样编辑后模型既有了新配置，也补上了 DB 记录。
    """
    client = get_client()
    wt = req.worker_type or req.model_type

    params = dict(req.params or {})
    params.setdefault("name", req.model_name)
    params.setdefault("provider", req.provider or "proxy/openai")
    if req.api_base:
        params["api_base"] = normalize_api_base(req.api_base)
    if req.api_key:
        params["api_key"] = req.api_key

    # 1) 停止旧实例（若在运行）。失败不中断——实例可能本来就没启动
    stop_body = {
        "model": req.model_name,
        "worker_type": wt,
        "host": req.host or "127.0.0.1",
        "port": req.port or 5670,
        "params": {},
    }
    stop_note = ""
    try:
        res = await client.post("/model/models/stop", stop_body)
        stop_data = res.json()
        if not stop_data.get("success"):
            stop_note = str(stop_data.get("err_msg", ""))
    except Exception as e:
        stop_note = str(e)

    # 2) 用新配置创建并启动（同时写入 DB）。
    # stop 是异步移除实例，若立即 create 会报 "worker instances is exist"，
    # 所以遇到该错误时等待后重试（最多 5 次，每次 2s）。
    create_body = {
        "model": req.model_name,
        "worker_type": wt,
        "host": req.host or "127.0.0.1",
        "port": req.port or 5670,
        "params": params,
    }
    import asyncio

    last_detail = ""
    for attempt in range(5):
        try:
            res = await client.post("/model/models", create_body)
            data = res.json()
            if data.get("success"):
                return {
                    "ok": True,
                    "message": "模型已用新配置重新启动并保存到数据库",
                    "stop_note": stop_note,
                }
            last_detail = str(data.get("err_msg", data))
        except HTTPException:
            raise
        except Exception as e:
            last_detail = str(e)
        if "instances is exist" not in last_detail:
            break
        await asyncio.sleep(2)

    detail = last_detail or "未知错误"
    if stop_note:
        detail += f"（停止旧实例时: {stop_note}）"
    raise HTTPException(400, detail=detail)


class ModelTestRequest(BaseModel):
    model_name: str = Field(..., description="模型名称")
    worker_type: str = Field("llm", description="Worker 类型")
    host: str = Field("127.0.0.1", description="主机")
    port: int = Field(5670, description="端口")
    # 可选：编辑弹窗中测试未保存的新配置时传入（不启动实例，直接测端点连通性）
    api_base: Optional[str] = Field(None, description="API 地址（可选，传入则直测该端点）")
    api_key: Optional[str] = Field(None, description="API Key（可选）")


@router.post("/test")
async def test_model(req: ModelTestRequest):
    """测试模型连通性 —— 真实推理测试。

    两种模式：
    1. 传 api_base + api_key：直接用 openai 协议向该端点发一条真实对话请求，
      不依赖 DB-GPT 实例。用于编辑弹窗中测试尚未保存的新配置。
      注意：从 qna-agent 容器内直测时走自身网络环境（有代理），与
      webserver 容器的网络环境不同，结果仅供参考；保存后建议再测一次。
    2. 不传 api_base：通过 DB-GPT /api/worker/generate 做端到端真实推理，
      覆盖 nginx 路由、api_key、模型路由全链路，能发现配置正确但链路不通的问题。
    """
    import os
    import httpx

    api_base = os.getenv("DBGPT_API_BASE", "http://127.0.0.1:5670/api/v2")
    base_url = api_base.rsplit("/api", 1)[0] if "/api" in api_base else api_base.rstrip("/")

    # 模式 1：直测用户填写的端点（真实对话请求）
    if req.api_base and req.api_key:
        ep = normalize_api_base(req.api_base)
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=60) as http:
                res = await http.post(
                    f"{ep}/chat/completions",
                    json={
                        "model": req.model_name,
                        "messages": [{"role": "user", "content": "回复两个字：成功"}],
                        "max_tokens": 512,  # 推理模型需要足够预算给思考过程
                        "stream": False,
                    },
                    headers={"Authorization": f"Bearer {req.api_key}"},
                )
                if res.status_code == 200:
                    data = res.json()
                    text = (
                        data.get("choices", [{}])[0].get("message", {}).get("content")
                        or ""
                    )
                    return {
                        "ok": True,
                        "message": f"连通正常，模型真实回复: {text[:50] or '(空)'}",
                        "metadata": {"endpoint": ep, "model": req.model_name},
                    }
                raise HTTPException(
                    400,
                    detail=f"端点返回 {res.status_code}: {res.text[:200]}",
                )
        except httpx.TimeoutException:
            raise HTTPException(408, detail="连通性测试超时（60s）：端点不可达或响应过慢")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(502, detail=f"连通性测试失败: {e}")

    # 模式 2：端到端推理测试（走 DB-GPT worker 全链路）
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=90) as http:
            res = await http.post(
                f"{base_url}/api/worker/generate",
                json={
                    "model": req.model_name,
                    # DB-GPT worker 消息角色必须小写：human/ai/system
                    # 'user'/'HUMAN' 会被静默丢弃 → 空 messages → 上游 502
                    "messages": [{"role": "human", "content": "回复两个字：成功"}],
                    "temperature": 0.1,
                    "max_new_tokens": 512,
                },
            )
            data = res.json()
            if data.get("error_code") == 0:
                content = data.get("content")
                text = ""
                if isinstance(content, list):
                    for item in content:
                        if item.get("type") == "text":
                            text = item.get("object", {}).get("data", "")
                            break
                elif isinstance(content, dict):
                    text = content.get("object", {}).get("data", "")
                return {
                    "ok": True,
                    "message": f"连通正常，模型真实回复: {(text or '(空)')[:50]}",
                    "metadata": {"model": req.model_name},
                }
            # error_code != 0 → 提取真实错误
            err_text = ""
            content = data.get("content")
            if isinstance(content, dict):
                err_text = content.get("object", {}).get("data", "")
            elif isinstance(content, list) and content:
                err_text = content[-1].get("object", {}).get("data", "")
            raise HTTPException(400, detail=f"推理失败: {err_text[:200] or data}")
    except httpx.TimeoutException:
        raise HTTPException(408, detail="连通性测试超时（90s）：模型未启动或 LLM 端点不可达")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"连通性测试失败: {e}")
