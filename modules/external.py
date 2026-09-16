# -*- coding: utf-8 -*-
"""外部平台兼容接口模块。

路由路径与外部平台（10.12.60.26:30541/knowledge）完全一致：
  POST /api/v1/agent/insert               —— 新增智能体（AgentInsertRequest 格式）
  POST /openPlatform/api/v1/model/config/page —— 模型配置分页
  POST /knowledge/llm/userDataSource/get/page/v1 —— 数据源配置分页
  POST /knowledge/api/v1/agent/detail     —— 应用配置详情
  POST /knowledge/llm/userDataSource/get/dbNamesByIds/v1 —— 批量查数据源
  POST /knowledge/llm/userDataSource/getTablesFromDataSource/v1 —— 获取表列表
  POST /knowledge/llm/userDataSource/table/getComments/v1 —— 获取表列信息
  POST /knowledge/llm/userDataSource/table/updateTableComments/v1 —— 修改表+列注释
  POST /knowledge/api/v1/agent/update     —— 编辑保存

数据来源为本地 DB-GPT 实例，响应格式参照外部平台。
"""
import json
import os
from typing import List, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text as sa_text

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


# ===========================================================================
# 辅助：MySQL 连接（读写 app_extra_config + recommend_question）
# ===========================================================================
def _get_mysql_conn():
    import pymysql
    return pymysql.connect(
        host=os.getenv("MYSQL_HOST", "db-gpt-db-1"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", "aa123456"),
        database=os.getenv("MYSQL_DATABASE", "dbgpt"),
        charset="utf8mb4",
    )


def _get_extra_config(app_code: str) -> dict:
    """从辅助表读取扩展配置，不存在返回空 dict。"""
    conn = _get_mysql_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT opening_message, guide_questions, model_config_extra, temperature, max_new_tokens "
                "FROM app_extra_config WHERE app_code = %s", (app_code,)
            )
            row = cur.fetchone()
            if not row:
                return {}
            return {
                "opening_message": row[0] or "",
                "guide_questions": json.loads(row[1]) if row[1] else [],
                "model_config_extra": json.loads(row[2]) if row[2] else {},
                "temperature": row[3],
                "max_new_tokens": row[4],
            }
    finally:
        conn.close()


def _upsert_extra_config(app_code: str, opening_message: str, guide_questions: list, model_config_extra: dict, temperature: float, max_new_tokens: int):
    """UPSERT 辅助表。"""
    conn = _get_mysql_conn()
    try:
        with conn.cursor() as cur:
            sql = (
                "INSERT INTO app_extra_config (app_code, opening_message, guide_questions, model_config_extra, temperature, max_new_tokens) "
                "VALUES (%s, %s, %s, %s, %s, %s) "
                "ON DUPLICATE KEY UPDATE "
                "opening_message = VALUES(opening_message), "
                "guide_questions = VALUES(guide_questions), "
                "model_config_extra = VALUES(model_config_extra), "
                "temperature = VALUES(temperature), "
                "max_new_tokens = VALUES(max_new_tokens)"
            )
            cur.execute(sql, (
                app_code,
                opening_message,
                json.dumps(guide_questions, ensure_ascii=False),
                json.dumps(model_config_extra, ensure_ascii=False),
                temperature,
                max_new_tokens,
            ))
        conn.commit()
    finally:
        conn.close()


async def _get_datasource_id_by_name(db_name: str) -> Optional[int]:
    """按 db_name 从 DB-GPT 数据源列表反查 datasource id。"""
    try:
        client = get_client()
        res = await client.get("/datasources")
        raw = res.json()
        items = raw.get("data") if raw.get("success") else []
        for item in items:
            if item.get("db_name") == db_name:
                return item.get("id")
    except Exception:
        pass
    return None


async def _get_datasource_detail_by_id(ds_id: int) -> dict:
    """按 id 从 DB-GPT serve 获取数据源详情（含连接参数）。"""
    async with httpx.AsyncClient(timeout=15, trust_env=False) as c:
        r = await c.get(f"http://db-gpt-webserver-1:5670/api/v2/serve/datasources/{ds_id}")
        d = r.json()
        if not d.get("success"):
            raise HTTPException(404, detail=f"数据源 {ds_id} 不存在")
        return d.get("data") or {}


# ===========================================================================
# 数据模型（第一章新增）
# ===========================================================================
class AgentDetailRequest(BaseModel):
    id: str = Field(..., description="app_code (UUID)")


class DbNamesByIdsRequest(BaseModel):
    ids: List[int] = Field(..., description="数据源 ID 列表")


class GetTablesRequest(BaseModel):
    id: int = Field(..., description="数据源 ID")
    tableNames: List[str] = Field(default_factory=list, description="表名过滤（空=全部）")


class GetTableCommentsRequest(BaseModel):
    id: int = Field(..., description="数据源 ID")
    tableName: str = Field(..., description="表名")


class UpdateTableCommentsRequest(BaseModel):
    id: int = Field(..., description="数据源 ID")
    tableName: str = Field(..., description="表名")
    tableComment: str = Field("", description="表注释")
    tableColumnInfos: List[dict] = Field(default_factory=list, description="列信息列表")


class AgentUpdateRequest(BaseModel):
    """外部平台 agent/update 请求体（冗余参数全量接收）。"""
    id: str = Field(..., description="app_code")
    appName: str = Field("", description="应用名称")
    remark: str = Field("", description="描述")
    openingMessage: str = Field("", description="开场白")
    guideQuestions: List[str] = Field(default_factory=list, description="引导问题")
    errorMessage: str = Field("")
    settingDescription: str = Field("")
    type: int = Field(2)
    limited: int = Field(0)
    managementMode: int = Field(3)
    sessionType: int = Field(10)
    appCategoryId: int = Field(0)
    icon: str = Field("")
    source: int = Field(0)
    isDefault: int = Field(0)
    visible: int = Field(1)
    enableSuggestedQuestions: int = Field(0)
    workflowId: str = Field("")
    workflowSite: str = Field("")
    varMap: dict = Field(default_factory=dict, description="含 modelConfig + dataSourceConfigs")


# ===========================================================================
# 接口 1.3: POST /knowledge/api/v1/agent/detail — 应用配置详情
# ===========================================================================
@router.post("/knowledge/api/v1/agent/detail")
async def agent_detail(req: AgentDetailRequest):
    """根据 app_code 返回应用完整配置信息（AgentDetailVO 格式）。"""
    try:
        # 1. 调 DB-GPT 获取 app 详情
        async with httpx.AsyncClient(timeout=15, trust_env=False) as c:
            r = await c.get(f"{_DBGPT_V1_BASE}/app/{req.id}")
            data = r.json()
        if not data.get("success"):
            raise HTTPException(404, detail=f"应用不存在: {req.id}")
        app = data.get("data") or {}

        # 2. 从 details[].resources 提取数据源列表
        ds_configs = []
        model_name = ""
        prompt_template = ""
        for detail in app.get("details") or []:
            for res in detail.get("resources") or []:
                if res.get("type") in ("database", "datasource"):
                    val = res.get("value", "")
                    try:
                        parsed = json.loads(val) if isinstance(val, str) else val
                    except Exception:
                        parsed = {}
                    db_name = parsed.get("db_name", "")
                    if db_name:
                        ds_id = await _get_datasource_id_by_name(db_name)
                        ds_configs.append({
                            "databaseId": ds_id or 0,
                            "dbName": db_name,
                            "tableNames": parsed.get("tables", []),
                        })
            # 提取模型名
            lsv = detail.get("llm_strategy_value", "")
            if lsv and not model_name:
                try:
                    if isinstance(lsv, str) and lsv.startswith("["):
                        arr = json.loads(lsv)
                        model_name = arr[0] if arr else lsv
                    else:
                        model_name = str(lsv)
                except Exception:
                    model_name = str(lsv)
            pt = detail.get("prompt_template")
            if pt and not prompt_template:
                prompt_template = pt

        # 3. 查辅助表获取扩展配置
        extra = _get_extra_config(req.id)

        # 4. 组装 modelConfig
        mc_extra = extra.get("model_config_extra") or {}
        model_config = {
            "modelType": model_name,
            "temperature": extra.get("temperature") or 0.6,
            "maxTokens": extra.get("max_new_tokens") or 4000,
            "topP": mc_extra.get("topP", 1.0),
            "frequencyPenalty": mc_extra.get("frequencyPenalty", 0.0),
            "presencePenalty": mc_extra.get("presencePenalty", 0.0),
            "enableThinking": mc_extra.get("enableThinking", False),
            "historyRounds": mc_extra.get("historyRounds", 3),
            "baseModel": mc_extra.get("baseModel", "openai"),
        }

        # 5. 组装响应
        result = {
            "id": req.id,
            "appId": req.id,
            "appName": app.get("app_name", ""),
            "remark": app.get("app_describe", ""),
            "openingMessage": extra.get("opening_message", ""),
            "guideQuestions": extra.get("guide_questions") or [],
            "icon": app.get("icon") or "",
            "type": 2,
            "limited": 0,
            "managementMode": 3,
            "sessionType": 10,
            "source": 0,
            "visible": 1,
            "enableSuggestedQuestions": 1 if (extra.get("guide_questions") or []) else 0,
            "appCategoryId": 0,
            "workflowId": "",
            "workflowSite": "",
            "errorMessage": "",
            "settingDescription": prompt_template or "",
            "varMap": {
                "modelConfig": model_config,
                "dataSourceConfigs": ds_configs,
                "knowledgeGraphConfigs": [],
            },
        }
        return {"code": 200, "msg": "Success", "success": True, "data": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"获取应用详情失败: {e}")


# ===========================================================================
# 接口 1.4: POST /knowledge/llm/userDataSource/get/dbNamesByIds/v1 — 批量查数据源
# ===========================================================================
@router.post("/knowledge/llm/userDataSource/get/dbNamesByIds/v1")
async def get_db_names_by_ids(req: DbNamesByIdsRequest):
    """根据数据源 ID 列表返回数据源简要信息。"""
    try:
        data = []
        for ds_id in req.ids:
            try:
                ds = await _get_datasource_detail_by_id(ds_id)
                params = ds.get("params", {})
                data.append({
                    "id": ds.get("id", ds_id),
                    "dbName": ds.get("comment") or ds.get("db_name", ""),
                    "name": ds.get("db_name", ""),
                    "ip": params.get("host", ""),
                    "port": params.get("port", 0),
                })
            except Exception:
                data.append({"id": ds_id, "dbName": "", "name": "", "ip": "", "port": 0})
        return {"code": 200, "msg": "Success", "success": True, "data": data}
    except Exception as e:
        raise HTTPException(502, detail=f"批量查数据源失败: {e}")


# ===========================================================================
# 接口 1.5.1: POST /knowledge/llm/userDataSource/getTablesFromDataSource/v1
# ===========================================================================
@router.post("/knowledge/llm/userDataSource/getTablesFromDataSource/v1")
async def get_tables_from_datasource(req: GetTablesRequest):
    """获取指定数据源的所有表名 + 表注释。"""
    try:
        ds = await _get_datasource_detail_by_id(req.id)
        params = ds.get("params", {})
        db_type = ds.get("type", "mysql")
        db_name = ds.get("db_name", "")

        from sqlalchemy import create_engine, inspect
        if db_type == "mysql":
            url = f"mysql+pymysql://{params.get('user','')}:{params.get('password','')}@{params.get('host','')}:{params.get('port',3306)}/{params.get('database',db_name)}?charset=utf8mb4"
        elif db_type == "sqlite":
            url = f"sqlite:///{params.get('path','')}"
        else:
            raise HTTPException(400, detail=f"暂不支持 {db_type} 类型")
        engine = create_engine(url, pool_pre_ping=True)
        inspector = inspect(engine)

        all_tables = inspector.get_table_names()
        # 过滤
        if req.tableNames:
            all_tables = [t for t in all_tables if t in req.tableNames]

        data = []
        for t in all_tables:
            comment = ""
            try:
                tc = inspector.get_table_comment(t)
                comment = tc.get("text") or ""
            except Exception:
                pass
            data.append({"tableName": t, "comment": comment})

        engine.dispose()
        return {"code": 200, "msg": "Success", "success": True, "data": data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"获取表列表失败: {e}")


# ===========================================================================
# 接口 1.5.2: POST /knowledge/llm/userDataSource/table/getComments/v1
# ===========================================================================
@router.post("/knowledge/llm/userDataSource/table/getComments/v1")
async def get_table_comments(req: GetTableCommentsRequest):
    """获取指定数据源中指定表的列信息。"""
    try:
        ds = await _get_datasource_detail_by_id(req.id)
        params = ds.get("params", {})
        db_type = ds.get("type", "mysql")
        db_name = ds.get("db_name", "")

        from sqlalchemy import create_engine, inspect
        if db_type == "mysql":
            url = f"mysql+pymysql://{params.get('user','')}:{params.get('password','')}@{params.get('host','')}:{params.get('port',3306)}/{params.get('database',db_name)}?charset=utf8mb4"
        elif db_type == "sqlite":
            url = f"sqlite:///{params.get('path','')}"
        else:
            raise HTTPException(400, detail=f"暂不支持 {db_type} 类型")
        engine = create_engine(url, pool_pre_ping=True)
        inspector = inspect(engine)

        data = []
        for col in inspector.get_columns(req.tableName):
            data.append({
                "columnName": col.get("name", ""),
                "dataType": str(col.get("type", "")),
                "maxLength": None,
                "isNullable": "YES" if col.get("nullable", True) else "NO",
                "defaultValue": str(col.get("default")) if col.get("default") is not None else None,
                "comment": col.get("comment") or "",
                "columnChName": None,
                "enumMap": None,
                "reverseEnumMap": {},
            })

        engine.dispose()
        return {"code": 200, "msg": "Success", "success": True, "data": data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"获取表列信息失败: {e}")


# ===========================================================================
# 接口 1.5.3: POST /knowledge/llm/userDataSource/table/updateTableComments/v1
# ===========================================================================
@router.post("/knowledge/llm/userDataSource/table/updateTableComments/v1")
async def update_table_comments(req: UpdateTableCommentsRequest):
    """修改表注释 + 列注释。"""
    try:
        ds = await _get_datasource_detail_by_id(req.id)
        params = ds.get("params", {})
        db_type = ds.get("type", "mysql")
        db_name = ds.get("db_name", "")

        if db_type != "mysql":
            raise HTTPException(400, detail="表注释修改仅支持 MySQL")

        from sqlalchemy import create_engine, inspect
        url = f"mysql+pymysql://{params.get('user','')}:{params.get('password','')}@{params.get('host','')}:{params.get('port',3306)}/{params.get('database',db_name)}?charset=utf8mb4"
        engine = create_engine(url, pool_pre_ping=True)
        inspector = inspect(engine)

        with engine.connect() as conn:
            # 1. 修改表注释
            if req.tableComment:
                table_escaped = req.tableName.replace("`", "``")
                comment_escaped = req.tableComment.replace("'", "''")
                conn.execute(sa_text(f"ALTER TABLE `{table_escaped}` COMMENT = '{comment_escaped}'"))

            # 2. 修改列注释
            if req.tableColumnInfos:
                # 查当前列信息（用于构造完整 MODIFY 语句）
                all_cols = {c["name"]: c for c in inspector.get_columns(req.tableName)}
                for col_info in req.tableColumnInfos:
                    col_name = col_info.get("columnName", "")
                    col_comment = col_info.get("comment", "")
                    if not col_name or not col_comment:
                        continue
                    existing = all_cols.get(col_name)
                    if not existing:
                        continue
                    col_type = str(existing["type"])
                    nullable = "" if existing.get("nullable", True) else " NOT NULL"
                    default = ""
                    if existing.get("default") is not None:
                        dv = str(existing["default"])
                        if not dv.startswith("'"):
                            dv = f"'{dv}'"
                        default = f" DEFAULT {dv}"
                    table_escaped = req.tableName.replace("`", "``")
                    col_escaped = col_name.replace("`", "``")
                    comment_escaped = col_comment.replace("'", "''")
                    sql = (
                        f"ALTER TABLE `{table_escaped}` "
                        f"MODIFY COLUMN `{col_escaped}` {col_type}"
                        f"{nullable}{default} COMMENT '{comment_escaped}'"
                    )
                    conn.execute(sa_text(sql))
            conn.commit()

        engine.dispose()
        return {"code": 200, "msg": "Success", "success": True, "data": "更新成功"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"修改表注释失败: {e}")


# ===========================================================================
# 接口 1.6: POST /knowledge/api/v1/agent/update — 编辑保存
# ===========================================================================
@router.post("/knowledge/api/v1/agent/update")
async def agent_update(req: AgentUpdateRequest):
    """编辑保存（含开场白、引导问题、模型配置、数据源+选表）。"""
    try:
        # 1. 获取现有 app 详情（保留原有字段）
        async with httpx.AsyncClient(timeout=15, trust_env=False) as c:
            r = await c.get(f"{_DBGPT_V1_BASE}/app/{req.id}")
            data = r.json()
        if not data.get("success"):
            raise HTTPException(404, detail=f"应用不存在: {req.id}")
        app = data.get("data") or {}

        # 2. 从 varMap 提取数据源配置
        var_map = req.varMap if isinstance(req.varMap, dict) else {}
        ds_configs = var_map.get("dataSourceConfigs") or []
        db_names = []
        db_tables = {}
        for ds in ds_configs:
            if isinstance(ds, dict):
                db_name = ds.get("dbName") or ds.get("name") or ""
                if db_name:
                    db_names.append(db_name)
                    tables = ds.get("tableNames") or []
                    if tables:
                        db_tables[db_name] = [str(t) for t in tables]

        # 3. 从 varMap.modelConfig 提取模型配置
        mc = var_map.get("modelConfig") or {}
        model_name = mc.get("modelType") or DEFAULT_MODEL
        temperature = mc.get("temperature", 0.6)
        max_tokens = mc.get("maxTokens", 4000)

        # 4. 构造 resources
        resources = []
        for db_name in db_names:
            value = {"name": "datasource", "db_name": db_name}
            if db_tables.get(db_name):
                value["tables"] = db_tables[db_name]
            resources.append({
                "type": "database", "name": f"数据源-{db_name}",
                "value": json.dumps(value, ensure_ascii=False),
                "is_dynamic": False, "context": None, "version": "v2",
            })

        # 5. 调 DB-GPT app/edit
        edit_body = {
            "app_code": req.id,
            "app_name": req.appName or app.get("app_name", ""),
            "app_describe": req.remark or app.get("app_describe", ""),
            "language": "zh",
            "team_mode": "native_app",
            "team_context": json.dumps({
                "chat_scene": "chat_react_agent",
                "scene_name": "chat_agent",
            }),
            "published": "true",
            "param_need": [{"type": "resource"}, {"type": "model"}, {"type": "temperature"}, {"type": "max_new_tokens"}],
            "details": [{
                "agent_name": "ReAct",
                "resources": resources,
                "llm_strategy": "Priority",
                "llm_strategy_value": model_name,
                "prompt_template": req.settingDescription or "",
                "temperate": temperature,
                "max_new_tokens": max_tokens,
            }],
        }
        async with httpx.AsyncClient(timeout=15, trust_env=False) as c:
            r2 = await c.post(f"{_DBGPT_V1_BASE}/app/edit", json=edit_body)
            d2 = r2.json()
        if not d2.get("success"):
            raise HTTPException(400, detail=str(d2.get("err_msg", d2)))

        # DB-GPT edit endpoint leaves published='false'; fix it so detail query works
        conn_fix = _get_mysql_conn()
        try:
            with conn_fix.cursor() as cur:
                cur.execute("UPDATE gpts_app SET published = 'true' WHERE app_code = %s", (req.id,))
            conn_fix.commit()
        finally:
            conn_fix.close()

        # 6. 写辅助表
        mc_extra = {
            "topP": mc.get("topP", 1.0),
            "frequencyPenalty": mc.get("frequencyPenalty", 0.0),
            "presencePenalty": mc.get("presencePenalty", 0.0),
            "enableThinking": mc.get("enableThinking", False),
            "historyRounds": mc.get("historyRounds", 3),
            "baseModel": mc.get("baseModel", "openai"),
        }
        _upsert_extra_config(
            app_code=req.id,
            opening_message=req.openingMessage,
            guide_questions=req.guideQuestions,
            model_config_extra=mc_extra,
            temperature=temperature,
            max_new_tokens=max_tokens,
        )

        # 7. 同步写 recommend_question 表（删除旧的 + 插入新的）
        # 读取 app 的 user_code 保持一致（DB-GPT detail 查询 JOIN 时 user_code 不匹配会报 JSON 解析错误）
        conn = _get_mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT user_code FROM gpts_app WHERE app_code = %s", (req.id,))
                row = cur.fetchone()
                app_user_code = row[0] if row else "001"
                cur.execute("DELETE FROM recommend_question WHERE app_code = %s", (req.id,))
                for q in (req.guideQuestions or []):
                    cur.execute(
                        "INSERT INTO recommend_question (app_code, question, chat_mode, valid, is_hot_question, user_code, params) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (req.id, q, "chat_react_agent", "Y", "N", app_user_code, "{}"),
                    )
            conn.commit()
        finally:
            conn.close()

        return {"code": 200, "msg": "Success", "success": True, "data": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"编辑智能体失败: {e}")
