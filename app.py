# -*- coding: utf-8 -*-
"""智能问数 Agent —— FastAPI 服务入口。

基于 DB-GPT SDK (dbgpt_client) 封装，对外暴露统一 REST 接口。

启动：
    uvicorn app:app --host 0.0.0.0 --port 8080

环境变量：
    DBGPT_API_BASE  — DB-GPT API 地址，默认 http://127.0.0.1:5670/api/v2
    DBGPT_API_KEY   — API Key（可选）
    MODEL            — 默认模型名
    TIMEOUT          — 请求超时秒数

接口模块：
    /ask              问答（NL2SQL / 知识库 / Flow / 流式）
    /datasources      数据源管理（CRUD / 类型 / 测试连接 / 刷新）
    /knowledge        知识库管理（空间 CRUD / 文档 CRUD / 同步 / 检索）
    /connectors       MCP 连接器管理（CRUD / 测试 / 工具 / 确认）
    /conversations    会话管理（新建 / 列表 / 删除 / 清空 / 历史 / 分页）
    /models           模型管理（类型 / 列表 / 启停）
    /flows            AWEL Flow 管理（CRUD）
    /prompts          Prompt 管理（CRUD / 类型目标）
    /apps             App 管理（列表 / 详情）
    /evaluation       评估管理（运行）
"""
import logging
import os
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# 确保当前目录在 Python 路径中，以便导入 core / modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules.qa import router as qa_router
from modules.datasource import router as ds_router
from modules.knowledge import router as kb_router
from modules.connector import router as conn_router
from modules.conversation import router as conv_router
from modules.file import router as file_router
from modules.model import router as model_router
from modules.flow import router as flow_router
from modules.prompt import router as prompt_router
from modules.app import router as app_router
from modules.external import router as external_router
from modules.evaluation import router as eval_router

logger = logging.getLogger("uvicorn.error")

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
DBGPT_API_BASE = os.getenv("DBGPT_API_BASE", "http://127.0.0.1:5670/api/v2")
DBGPT_API_KEY = os.getenv("DBGPT_API_KEY", "")
MODEL = os.getenv("MODEL", "TS-MOMA/DeepSeek-V4-Flash")
TIMEOUT = float(os.getenv("TIMEOUT", "300"))

# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="智能问数 Agent",
    description="基于 DB-GPT SDK 封装的统一智能问数服务",
    version="1.0.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载路由
app.include_router(qa_router)
app.include_router(ds_router)
app.include_router(kb_router)
app.include_router(conn_router)
app.include_router(conv_router)
app.include_router(file_router)
app.include_router(model_router)
app.include_router(flow_router)
app.include_router(prompt_router)
app.include_router(app_router)
app.include_router(external_router)
app.include_router(eval_router)


@app.get("/")
async def root():
    """根路径 —— 返回服务信息。"""
    return {
        "service": "智能问数 Agent",
        "version": "1.0.0",
        "dbgpt_api_base": DBGPT_API_BASE,
        "model": MODEL,
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    """健康检查。"""
    return {
        "status": "ok",
        "model": MODEL,
        "dbgpt": DBGPT_API_BASE,
    }


# ---------------------------------------------------------------------------
# 静态文件 & 前端页面（禁用缓存，确保 JS/CSS 修改即时生效）
# ---------------------------------------------------------------------------
_static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


class NoCacheStaticFiles(StaticFiles):
    """StaticFiles with no-cache headers to prevent browser caching of JS/CSS."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        return response


app.mount("/static", NoCacheStaticFiles(directory=_static_dir), name="static")


@app.get("/ui")
async def ui():
    """前端界面入口（同样禁用缓存）。"""
    from fastapi.responses import HTMLResponse
    html_path = os.path.join(_static_dir, "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()
    return HTMLResponse(content=content, headers={
        "Cache-Control": "no-store, no-cache, must-revalidate",
        "Pragma": "no-cache",
    })
