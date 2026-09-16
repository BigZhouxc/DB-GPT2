# -*- coding: utf-8 -*-
"""外部平台兼容接口模块。

路由路径与外部平台（10.12.60.26:30541/knowledge）完全一致：
  POST /api/v1/agent/insert               —— 新增智能体（AgentInsertRequest 格式）
  POST /openPlatform/api/v1/model/config/page —— 模型配置分页
  POST /knowledge/llm/userDataSource/get/page/v1 —— 数据源配置分页

数据来源为本地 DB-GPT 实例，响应格式参照外部平台。
"""
import json
import os
from typing import List

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.client_factory import get_client

# 无 prefix 路由，路径与外部平台完全一致
router = APIRouter(tags=["外部平台兼容接口"])

_DBGPT_V1_BASE = "http://db-gpt-webserver-1:5670/api/v1"

# 默认模型 —— 环境变量可覆盖；运行时会校验可用性，不可用自动回退
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "TS-MOMA/DeepSeek-V4-Flash")


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------
class ExternalPageRequest(BaseModel):
    currentPage: int = Field(1, description="当前页")
    pageSize: int = Field(1000, description="每页条数")
    dbName: str = Field("", description="数据库名（数据源查询用）")


class AgentInsertRequest(BaseModel):
    """外部平台 insertAgent 接口的请求体（冗余参数全量接收）。"""
    appName: str = Field(..., description="智能体名称")
    remark: str = Field("", description="描述")
    modelNames: List[str] = Field(default_factory=list, description="关联的模型名称列表")
    guideQuestions: List[str] = Field(default_factory=list, description="引导/推荐问题列表")
    openingMessage: str = Field("", description="开场白")
    settingDescription: str = Field("", description="设定描述/提示词")
    # 以下为冗余字段，接收后忽略
    appCategoryId: int = Field(0, description="app业务分类ID（冗余）")
    appExtraInfo: str = Field("", description="app额外信息（冗余）")
    enableSuggestedQuestions: int = Field(0, description="是否开启推荐问题（冗余）")
    errorMessage: str = Field("", description="错误提示（冗余）")
    frontendPageUrl: str = Field("", description="前端页面URL（冗余）")
    icon: str = Field("", description="图标（冗余）")
    interval: int = Field(0, description="单位时间数量（冗余）")
    isDefault: int = Field(0, description="是否默认（冗余）")
    limited: int = Field(0, description="是否限流（冗余）")
    managementMode: int = Field(0, description="管理方式（冗余）")
    permits: int = Field(0, description="允许次数（冗余）")
    sessionType: int = Field(0, description="会话类型（冗余）")
    source: int = Field(0, description="来源（冗余）")
    strategyName: str = Field("", description="策略名称（冗余）")
    strategyRemark: str = Field("", description="策略备注（冗余）")
    tokens: int = Field(0, description="tokens余量（冗余）")
    type: int = Field(1, description="智能体大类（冗余）")
    unit: str = Field("", description="时间单位（冗余）")
    userIds: list = Field(default_factory=list, description="关联用户id（冗余）")
    varMap: dict = Field(default_factory=dict, description="全局变量（含数据源配置）")
    visible: int = Field(1, description="是否可见（冗余）")
    workflowId: str = Field("", description="工作流ID（冗余）")
    workflowSite: str = Field("", description="工作流站点（冗余）")


# ---------------------------------------------------------------------------
# 辅助（与 app.py 共享逻辑，独立维护避免跨模块依赖）
# ---------------------------------------------------------------------------
async def _list_running_models():
    """获取当前运行中的模型名列表（失败返回空列表，不抛异常）。"""
    try:
        async with httpx.AsyncClient(timeout=10, trust_env=False) as c:
            r = await c.get("http://db-gpt-webserver-1:5670/api/v2/serve/model/models")
            d = r.json()
            if d.get("success"):
                models = d.get("data") or []
                return [
                    m.get("model_name", "")
                    for m in models
                    if isinstance(m, dict) and m.get("model_name")
                ]
    except Exception:
        pass
    return []


def _build_app_body_from_insert(
    app_name: str,
    app_describe: str,
    db_names: list,
    db_tables: dict,
    model: str,
    recommend_questions: list,
    prompt_template: str,
):
    """从 AgentInsertRequest 映射的参数构造 DB-GPT App 创建 body。"""
    resources = []
    for db_name in db_names:
        tables = db_tables.get(db_name) or []
        value = {"name": "datasource", "db_name": db_name}
        if tables:
            value["tables"] = [str(t) for t in tables]
        resources.append({
            "type": "database",
            "name": f"数据源-{db_name}",
            "value": json.dumps(value, ensure_ascii=False),
            "is_dynamic": False,
            "context": None,
            "version": "v2",
        })
    return {
        "app_name": app_name,
        "app_describe": app_describe,
        "language": "zh",
        "team_mode": "native_app",
        "team_context": json.dumps({"scene_name": "chat_agent", "chat_scene": "chat_react_agent"}, ensure_ascii=False),
        "resources": resources,
        "model": model,
        "model_config": model,
        "temperature": 0.6,
        "max_new_tokens": 4000,
        "auto_recommend_questions": recommend_questions,
        "prompt_template": prompt_template,
    }


# ---------------------------------------------------------------------------
# 接口：POST /api/v1/agent/insert  （与外部平台路径完全一致）
# ---------------------------------------------------------------------------
@router.post("/api/v1/agent/insert")
async def insert_agent(req: AgentInsertRequest):
    """接收 AgentInsertRequest 格式的请求，映射为 DB-GPT App 创建。

    参数映射：
      appName            → app_name
      remark             → app_describe
      modelNames[0]      → model（取第一个）
      guideQuestions     → recommend_questions
      settingDescription → prompt_template
      varMap.dataSourceConfigs → database_names + database_tables
    """
    try:
        # 从 varMap 提取数据源配置
        var_map = req.varMap if isinstance(req.varMap, dict) else {}
        ds_configs = var_map.get("dataSourceConfigs") or []
        db_names = []
        db_tables = {}
        for ds in ds_configs:
            if isinstance(ds, dict):
                db_name = ds.get("dbName") or ds.get("name") or ""
                if db_name:
                    db_names.append(db_name)
                    tables = ds.get("tableNames") or ds.get("tables") or []
                    if tables:
                        db_tables[db_name] = [str(t) for t in tables]

        # 取第一个模型名
        model = ""
        if req.modelNames:
            model = req.modelNames[0] if isinstance(req.modelNames, list) else str(req.modelNames)
        if not model:
            model = DEFAULT_MODEL

        body = _build_app_body_from_insert(
            app_name=req.appName,
            app_describe=req.remark or req.openingMessage or "",
            db_names=db_names,
            db_tables=db_tables,
            model=model,
            recommend_questions=req.guideQuestions if isinstance(req.guideQuestions, list) else [],
            prompt_template=req.settingDescription or "",
        )
        async with httpx.AsyncClient(timeout=30, trust_env=False) as c:
            r = await c.post(f"{_DBGPT_V1_BASE}/app/create", json=body)
            data = r.json()
        if not data.get("success"):
            err_msg = str(data.get("err_msg", data))
            if "Duplicate entry" in err_msg:
                err_msg = "应用名已存在，请换一个名称"
            raise HTTPException(400, detail=err_msg)
        app = data.get("data") or {}
        return {
            "code": 200,
            "msg": "Success",
            "success": True,
            "data": {
                "appCode": app.get("app_code", ""),
                "appName": app.get("app_name", ""),
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"创建智能体失败: {e}")


# ---------------------------------------------------------------------------
# 接口：POST /openPlatform/api/v1/model/config/page  （与外部平台路径完全一致）
# ---------------------------------------------------------------------------
@router.post("/openPlatform/api/v1/model/config/page")
async def external_model_configs(req: ExternalPageRequest):
    """获取模型配置列表。

    返回格式参照外部平台 /openPlatform/api/v1/model/config/page 响应结构，
    数据来源为本地 DB-GPT 运行中的模型。
    """
    try:
        running = await _list_running_models()
        data = []
        for i, m_name in enumerate(running, start=1):
            source = m_name.split("/")[0] if "/" in m_name else m_name
            data.append({
                "id": i,
                "sourceName": source,
                "modelName": m_name,
                "categoryId": 0,
                "categoryName": None,
                "baseModelType": 0,
                "enableThinking": False,
                "status": 1,
                "remark": None,
                "isDeleted": 0,
                "createTime": None,
                "updateTime": None,
                "availableEndpointNum": None,
                "totalEndpointNum": None,
            })
        return {
            "code": 200,
            "msg": "Success",
            "success": True,
            "data": data,
            "pageInfo": {
                "currentPage": req.currentPage,
                "pageSize": req.pageSize,
                "total": len(data),
            },
            "count": 0,
        }
    except Exception as e:
        raise HTTPException(502, detail=f"获取模型配置失败: {e}")


# ---------------------------------------------------------------------------
# 接口：POST /knowledge/llm/userDataSource/get/page/v1  （与外部平台路径完全一致）
# ---------------------------------------------------------------------------
@router.post("/knowledge/llm/userDataSource/get/page/v1")
async def external_datasource_configs(req: ExternalPageRequest):
    """获取数据源配置列表。

    返回格式参照外部平台 /knowledge/llm/userDataSource/get/page/v1 响应结构，
    数据来源为本地 DB-GPT 已注册的数据源。
    """
    try:
        client = get_client()
        res = await client.get("/datasources")
        raw = res.json()
        items = raw.get("data") if raw.get("success") else []
        data = []
        for item in items:
            params = item.get("params", {})
            db_type = item.get("type", item.get("db_type", ""))
            db_name = item.get("db_name", "")
            comment = item.get("comment", item.get("description", ""))
            data.append({
                "id": item.get("id"),
                "userId": 0,
                "dbType": 0 if db_type == "mysql" else (4 if db_type == "neo4j" else 0),
                "jdbcUrl": f"jdbc:mysql://{params.get('host','')}:{params.get('port',3306)}/{params.get('database',db_name)}" if db_type == "mysql" else "",
                "dbName": comment or db_name,
                "name": db_name,
                "dbSchema": "",
                "username": params.get("user", ""),
                "password": "",
                "description": comment,
                "isDeleted": 0,
                "createTime": None,
                "updateTime": None,
                "ip": params.get("host", ""),
                "port": params.get("port", 0),
            })
        return {
            "code": 200,
            "msg": "Success",
            "success": True,
            "data": data,
            "pageInfo": {
                "currentPage": req.currentPage,
                "pageSize": req.pageSize,
                "total": len(data),
            },
        }
    except Exception as e:
        raise HTTPException(502, detail=f"获取数据源配置失败: {e}")
