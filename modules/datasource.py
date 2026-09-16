# -*- coding: utf-8 -*-
"""数据源管理模块 —— 封装 DB-GPT SDK datasource 函数 + serve 通用 HTTP 路由。

SDK 直接封装：list / get / create / update / delete
Serve 通用 HTTP：datasource-types / test-connection / refresh
"""
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from dbgpt_client.datasource import (
    create_datasource,
    delete_datasource,
    get_datasource,
    list_datasource,
    update_datasource,
)
from dbgpt_client.schema import DatasourceModel

from core.client_factory import get_client

router = APIRouter(prefix="/datasources", tags=["数据源管理"])


# ---------------------------------------------------------------------------
# Pydantic 请求模型
# ---------------------------------------------------------------------------
class DatasourceCreateRequest(BaseModel):
    db_type: str = Field(..., description="数据库类型: sqlite / mysql / duckdb 等")
    db_name: str = Field(..., description="数据库名")
    db_path: str = Field("", description="文件型数据库路径（sqlite 用）")
    db_host: str = Field("", description="数据库主机地址")
    db_port: int = Field(0, description="数据库端口")
    db_user: str = Field("", description="数据库用户名")
    db_pwd: str = Field("", description="数据库密码")
    comment: str = Field("", description="备注说明")


class DatasourceUpdateRequest(DatasourceCreateRequest):
    id: int = Field(..., description="数据源 ID")


class TestConnectionRequest(BaseModel):
    db_type: str = Field(..., description="数据库类型")
    db_name: str = Field(..., description="数据库名")
    db_path: str = Field("", description="文件路径")
    db_host: str = Field("", description="主机地址")
    db_port: int = Field(0, description="端口")
    db_user: str = Field("", description="用户名")
    db_pwd: str = Field("", description="密码")
    datasource_id: Optional[str] = Field(None, description="数据源 ID（密码为空时用此 ID 从 serve 获取真实密码）")


# ---------------------------------------------------------------------------
# SDK 直接封装的接口
# ---------------------------------------------------------------------------
@router.get("")
@router.get("/")
async def list_all():
    """列出所有已注册的数据源。

    注意：SDK 的 list_datasource 用 DatasourceModel 解析，但 serve 返回的字段名
    是 `type` 而非 `db_type`，直接用 SDK 函数会报 validation error。
    这里改用通用 HTTP 调用，直接取原始 JSON。
    """
    try:
        client = get_client()
        res = await client.get("/datasources")
        data = res.json()
        if not data.get("success"):
            raise HTTPException(502, detail=str(data))
        items = data["data"]
        # serve 返回字段名: id, type, db_name, db_host, db_port, db_path, db_user, comment, file_path
        out = []
        for item in items:
            params = item.get("params", {})
            out.append({
                "id": item.get("id"),
                "db_type": item.get("type", item.get("db_type", "")),
                "db_name": item.get("db_name", ""),
                "db_host": params.get("host", item.get("db_host", "")),
                "db_port": params.get("port", item.get("db_port", 0)),
                "db_path": params.get("path", item.get("file_path", item.get("db_path", ""))),
                "db_user": params.get("user", item.get("db_user", "")),
                "comment": item.get("comment", item.get("description", "")),
            })
        return {"ok": True, "datasources": out}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"获取数据源列表失败: {e}")


@router.get("/{datasource_id}")
async def get_one(datasource_id: str):
    """获取指定数据源详情。

    同样用通用 HTTP 调用避免 SDK 的 DatasourceModel 字段映射问题。
    """
    try:
        client = get_client()
        res = await client.get(f"/datasources/{datasource_id}")
        data = res.json()
        if not data.get("success"):
            raise HTTPException(404, detail=str(data))
        item = data["data"]
        params = item.get("params", {})
        return {
            "ok": True,
            "datasource": {
                "id": item.get("id"),
                "db_type": item.get("type", item.get("db_type", "")),
                "db_name": item.get("db_name", ""),
                "db_path": params.get("path", item.get("file_path", item.get("db_path", ""))),
                "db_host": params.get("host", item.get("db_host", "")),
                "db_port": params.get("port", item.get("db_port", 0)),
                "db_user": params.get("user", item.get("db_user", "")),
                "comment": item.get("comment", item.get("description", "")),
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"获取数据源失败: {e}")


@router.post("")
@router.post("/")
async def create(req: DatasourceCreateRequest):
    """新建数据源。

    用通用 HTTP 调用（非 SDK），因为 DB-GPT serve 返回的字段名是 `type` 而非
    `db_type`，SDK 的 DatasourceModel 解析会报 validation error。
    """
    try:
        client = get_client()
        # 直接用 client.post 打 serve 接口，不走 SDK 的 create_datasource
        body = req.model_dump()
        res = await client.post("/datasources", body)
        data = res.json()
        if not data.get("success"):
            raise HTTPException(400, detail=str(data.get("err_msg", data)))
        return {"ok": True, "datasource": {"db_name": req.db_name, "comment": req.comment}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"创建数据源失败: {e}")


@router.put("")
@router.put("/")
async def update(req: DatasourceUpdateRequest):
    """更新数据源。"""
    try:
        client = get_client()
        body = req.model_dump()
        res = await client.put("/datasources", body)
        data = res.json()
        if not data.get("success"):
            raise HTTPException(400, detail=str(data.get("err_msg", data)))
        return {"ok": True, "datasource": {"id": req.id, "db_name": req.db_name, "comment": req.comment}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"更新数据源失败: {e}")


@router.delete("/{datasource_id}")
async def delete_one(datasource_id: str):
    """删除数据源。

    用通用 HTTP 调用（非 SDK），因为 DB-GPT serve 删除成功后返回 data: None，
    SDK 的 DatasourceModel(**None) 会报错。
    """
    try:
        client = get_client()
        res = await client.delete(f"/datasources/{datasource_id}")
        data = res.json()
        if not data.get("success"):
            raise HTTPException(400, detail=str(data.get("err_msg", data)))
        return {"ok": True, "datasource": {"id": datasource_id}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"删除数据源失败: {e}")


# ---------------------------------------------------------------------------
# Serve 通用 HTTP 调用（SDK 未封装的接口）
# ---------------------------------------------------------------------------
class DatasourceCommentRequest(BaseModel):
    comment: str = Field("", description="数据库描述/备注")


@router.put("/{datasource_id}/comment")
async def update_comment(datasource_id: str, req: DatasourceCommentRequest):
    """更新数据源的数据库描述（comment）。

    轻量接口：直接 UPDATE connect_config.comment，只动这一个字段，
    不走 PUT /datasources 整体更新（避免误改连接信息）。
    """
    try:
        import pymysql
        import os
        conn = pymysql.connect(
            host=os.getenv("MYSQL_HOST", "db-gpt-db-1"),
            port=int(os.getenv("MYSQL_PORT", "3306")),
            user=os.getenv("MYSQL_USER", "root"),
            password=os.getenv("MYSQL_PASSWORD", "aa123456"),
            database=os.getenv("MYSQL_DATABASE", "dbgpt"),
            charset="utf8mb4",
        )
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE connect_config SET comment = %s, gmt_modified = NOW() WHERE id = %s",
                    (req.comment, int(datasource_id)),
                )
            conn.commit()
            if cursor.rowcount == 0:
                raise HTTPException(404, detail=f"数据源 {datasource_id} 不存在")
        finally:
            conn.close()
        return {"ok": True, "id": datasource_id, "comment": req.comment}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"更新数据库描述失败: {e}")


@router.get("/types/list")
async def list_types():
    """查看支持的数据源类型。

    serve 路由: GET /datasource-types
    """
    try:
        client = get_client()
        res = await client.get("/datasource-types")
        data = res.json()
        if data.get("success"):
            return {"ok": True, "types": data["data"]}
        raise HTTPException(502, detail=str(data))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"获取数据源类型失败: {e}")


@router.post("/test-connection")
async def test_connection(req: TestConnectionRequest):
    """测试数据库连接。

    如果密码为空且提供了 datasource_id，从 DB-GPT serve 获取真实密码。
    然后转换为 serve 格式 {type, params} 调用 DB-GPT test-connection。
    """
    try:
        client = get_client()
        db_type = req.db_type
        db_host = req.db_host
        db_port = req.db_port
        db_user = req.db_user
        db_pwd = req.db_pwd
        db_path = req.db_path
        db_name = req.db_name

        # 如果密码为空且指定了 datasource_id，从 serve 获取完整连接信息
        if not db_pwd and req.datasource_id:
            try:
                params = await _get_db_params(req.datasource_id)
                if params.get("db_type") == "mysql":
                    db_host = params.get("host", db_host)
                    db_port = params.get("port", db_port)
                    db_user = params.get("user", db_user)
                    db_pwd = params.get("password", "")
                elif params.get("db_type") == "sqlite":
                    db_path = params.get("path", db_path)
            except Exception:
                pass

        # 转换为 serve 格式 {type, params}
        if db_type == "mysql":
            serve_body = {
                "type": "mysql",
                "params": {
                    "host": db_host, "port": db_port,
                    "user": db_user, "password": db_pwd,
                    "database": db_name,
                },
            }
        elif db_type == "sqlite":
            serve_body = {
                "type": "sqlite",
                "params": {"path": db_path},
            }
        else:
            serve_body = {
                "type": db_type,
                "params": {"host": db_host, "port": db_port, "user": db_user, "password": db_pwd, "database": db_name},
            }

        res = await client.post("/datasources/test-connection", serve_body)
        data = res.json()
        if data.get("success"):
            return {"ok": True, "connected": data["data"]}
        raise HTTPException(400, detail=str(data))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"测试连接失败: {e}")


@router.post("/{datasource_id}/refresh")
async def refresh(datasource_id: str):
    """刷新数据源元信息。

    serve 路由: POST /datasources/{id}/refresh
    """
    try:
        client = get_client()
        res = await client.post(f"/datasources/{datasource_id}/refresh", {})
        data = res.json()
        if data.get("success"):
            return {"ok": True, "refreshed": data["data"]}
        raise HTTPException(400, detail=str(data))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"刷新数据源失败: {e}")


# ==========================================================================
# Schema 预览（不依赖 datasource_id，用连接参数直接查表结构）
# ==========================================================================

def _create_engine_from_params(db_type, db_host, db_port, db_user, db_pwd, db_name, db_path):
    """根据连接参数创建 SQLAlchemy engine。"""
    from sqlalchemy import create_engine
    if db_type == "mysql":
        url = f"mysql+pymysql://{db_user}:{db_pwd}@{db_host}:{db_port}/{db_name}?charset=utf8mb4"
        return create_engine(url, pool_pre_ping=True)
    elif db_type == "sqlite":
        return create_engine(f"sqlite:///{db_path}")
    else:
        raise ValueError(f"Unsupported db_type: {db_type}")


@router.post("/schema-preview")
async def schema_preview(req: TestConnectionRequest):
    """用连接参数直接查表结构 + comment（不依赖已创建的数据源）。

    用于添加数据源弹窗中测试连接成功后预览 schema。
    """
    try:
        db_type = req.db_type
        db_host = req.db_host
        db_port = req.db_port
        db_user = req.db_user
        db_pwd = req.db_pwd
        db_path = req.db_path
        db_name = req.db_name

        # 如果密码为空且指定了 datasource_id，从 serve 获取
        if not db_pwd and req.datasource_id:
            try:
                params = await _get_db_params(req.datasource_id)
                if params.get("db_type") == "mysql":
                    db_host = params.get("host", db_host)
                    db_port = params.get("port", db_port)
                    db_user = params.get("user", db_user)
                    db_pwd = params.get("password", "")
                elif params.get("db_type") == "sqlite":
                    db_path = params.get("path", db_path)
            except Exception:
                pass

        engine = _create_engine_from_params(db_type, db_host, db_port, db_user, db_pwd, db_name, db_path)

        from sqlalchemy import inspect, MetaData
        from sqlalchemy.schema import CreateTable

        inspector = inspect(engine)
        metadata = MetaData()
        metadata.reflect(bind=engine)

        tables = []
        for table in metadata.sorted_tables:
            if db_type == "sqlite" and table.name.startswith("sqlite_"):
                continue
            create_sql = str(CreateTable(table).compile(engine)).strip()
            table_comment = ""
            try:
                tc = inspector.get_table_comment(table.name)
                table_comment = tc.get("text") or ""
            except Exception:
                pass
            columns = []
            for col in inspector.get_columns(table.name):
                columns.append({
                    "name": col["name"], "type": str(col["type"]),
                    "comment": col.get("comment") or "",
                    "is_primary_key": False,
                    "nullable": col.get("nullable", True),
                })
            try:
                pk_cols = inspector.get_pk_constraint(table.name)
                for col_name in pk_cols.get("constrained_columns", []):
                    for col in columns:
                        if col["name"] == col_name:
                            col["is_primary_key"] = True
            except Exception:
                pass
            tables.append({
                "table_name": table.name,
                "table_comment": table_comment,
                "ddl": create_sql,
                "columns": columns,
            })
        return {"ok": True, "schema": {"db_name": db_name, "db_type": db_type, "tables": tables}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"预览表结构失败: {e}")


# ==========================================================================
# Schema & Comment 管理（直接操作目标数据库，不走 DB-GPT SDK）
# ==========================================================================

async def _get_db_params(datasource_id: str) -> dict:
    """从 DB-GPT serve 获取数据源连接参数（含密码）。"""
    client = get_client()
    res = await client.get(f"/datasources/{datasource_id}")
    data = res.json()
    if not data.get("success"):
        raise HTTPException(404, detail=f"数据源 {datasource_id} 不存在")
    item = data["data"]
    params = item.get("params", {})
    db_type = item.get("type", item.get("db_type", ""))
    db_name = item.get("db_name", "")
    if db_type == "mysql":
        return {
            "db_type": "mysql",
            "db_name": db_name,
            "host": params.get("host", ""),
            "port": params.get("port", 3306),
            "user": params.get("user", ""),
            "password": params.get("password", ""),
            "database": params.get("database", db_name),
        }
    elif db_type == "sqlite":
        return {
            "db_type": "sqlite",
            "db_name": db_name,
            "path": params.get("path", ""),
        }
    else:
        raise HTTPException(400, detail=f"暂不支持 {db_type} 类型的 comment 管理")


def _create_engine(params: dict):
    """根据连接参数创建 SQLAlchemy engine。"""
    from sqlalchemy import create_engine
    if params["db_type"] == "mysql":
        url = f"mysql+pymysql://{params['user']}:{params['password']}@{params['host']}:{params['port']}/{params['database']}?charset=utf8mb4"
        return create_engine(url, pool_pre_ping=True)
    elif params["db_type"] == "sqlite":
        return create_engine(f"sqlite:///{params['path']}")
    else:
        raise ValueError(f"Unsupported db_type: {params['db_type']}")


@router.get("/{datasource_id}/schema")
async def get_schema(datasource_id: str):
    """获取数据源的表结构 + 表/列 comment 信息。

    返回所有表的 CREATE TABLE DDL、表注释、列注释、示例数据。
    """
    try:
        from sqlalchemy import inspect, MetaData
        from sqlalchemy.schema import CreateTable
        import textwrap

        params = await _get_db_params(datasource_id)
        engine = _create_engine(params)
        inspector = inspect(engine)
        metadata = MetaData()
        metadata.reflect(bind=engine)

        tables = []
        for table in metadata.sorted_tables:
            # 跳过 sqlite 系统表
            if params["db_type"] == "sqlite" and table.name.startswith("sqlite_"):
                continue

            # CREATE TABLE DDL
            create_sql = str(CreateTable(table).compile(engine)).strip()

            # 表注释
            table_comment = ""
            try:
                tc = inspector.get_table_comment(table.name)
                table_comment = tc.get("text") or ""
            except Exception:
                pass

            # 列信息
            columns = []
            for col in inspector.get_columns(table.name):
                columns.append({
                    "name": col["name"],
                    "type": str(col["type"]),
                    "comment": col.get("comment") or "",
                    "is_primary_key": False,
                    "nullable": col.get("nullable", True),
                    "default": str(col.get("default")) if col.get("default") else "",
                })

            # 标记主键列
            try:
                pk_cols = inspector.get_pk_constraint(table.name)
                for col_name in pk_cols.get("constrained_columns", []):
                    for col in columns:
                        if col["name"] == col_name:
                            col["is_primary_key"] = True
            except Exception:
                pass

            tables.append({
                "table_name": table.name,
                "table_comment": table_comment,
                "ddl": create_sql,
                "columns": columns,
            })

        return {
            "ok": True,
            "schema": {
                "db_name": params["db_name"],
                "db_type": params["db_type"],
                "tables": tables,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"获取表结构失败: {e}")


class TableCommentItem(BaseModel):
    table_name: str = Field(..., description="表名")
    comment: str = Field("", description="表注释")


class TableCommentUpdateRequest(BaseModel):
    comments: List[TableCommentItem] = Field(..., description="表注释列表")


@router.put("/{datasource_id}/schema/tables")
async def update_table_comments(datasource_id: str, req: TableCommentUpdateRequest):
    """批量修改表的 comment（ALTER TABLE ... COMMENT）。

    仅支持 MySQL。SQLite 不支持 TABLE COMMENT。
    """
    try:
        params = await _get_db_params(datasource_id)
        if params["db_type"] != "mysql":
            raise HTTPException(400, detail="表注释仅支持 MySQL")

        engine = _create_engine(params)
        results = []
        with engine.connect() as conn:
            for item in req.comments:
                table = item.table_name.replace("`", "``")
                comment = item.comment.replace("'", "''")
                sql = f"ALTER TABLE `{table}` COMMENT = '{comment}'"
                try:
                    conn.execute(text(sql))
                    results.append({"table_name": item.table_name, "ok": True})
                except Exception as e:
                    results.append({"table_name": item.table_name, "ok": False, "error": str(e)})
            conn.commit()

        return {"ok": True, "results": results}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"修改表注释失败: {e}")


class ColumnCommentItem(BaseModel):
    table_name: str = Field(..., description="表名")
    column_name: str = Field(..., description="列名")
    comment: str = Field("", description="列注释")


class ColumnCommentUpdateRequest(BaseModel):
    comments: List[ColumnCommentItem] = Field(..., description="列注释列表")


@router.put("/{datasource_id}/schema/columns")
async def update_column_comments(datasource_id: str, req: ColumnCommentUpdateRequest):
    """批量修改列的 comment（ALTER TABLE ... MODIFY COLUMN）。

    仅支持 MySQL。MODIFY COLUMN 需要完整的列定义（类型 + nullable + default），
    所以此接口先查列信息再拼 ALTER。
    """
    try:
        from sqlalchemy import inspect as sqla_inspect

        params = await _get_db_params(datasource_id)
        if params["db_type"] != "mysql":
            raise HTTPException(400, detail="列注释仅支持 MySQL")

        engine = _create_engine(params)
        inspector = sqla_inspect(engine)

        # 按表分组
        by_table = {}
        for item in req.comments:
            by_table.setdefault(item.table_name, []).append(item)

        results = []
        with engine.connect() as conn:
            for table_name, col_items in by_table.items():
                # 查当前列信息
                all_cols = {c["name"]: c for c in inspector.get_columns(table_name)}
                for col_item in col_items:
                    col = all_cols.get(col_item.column_name)
                    if not col:
                        results.append({
                            "table_name": table_name,
                            "column_name": col_item.column_name,
                            "ok": False,
                            "error": "列不存在",
                        })
                        continue

                    # 构造 MODIFY COLUMN 语句
                    col_type = str(col["type"])
                    nullable = "" if col.get("nullable", True) else " NOT NULL"
                    default = ""
                    if col.get("default") is not None:
                        default_val = str(col["default"])
                        if not default_val.startswith("'"):
                            default_val = f"'{default_val}'"
                        default = f" DEFAULT {default_val}"
                    comment = col_item.comment.replace("'", "''")
                    table_escaped = table_name.replace("`", "``")
                    col_escaped = col_item.column_name.replace("`", "``")

                    sql = (
                        f"ALTER TABLE `{table_escaped}` "
                        f"MODIFY COLUMN `{col_escaped}` {col_type}"
                        f"{nullable}{default} COMMENT '{comment}'"
                    )
                    try:
                        conn.execute(text(sql))
                        results.append({
                            "table_name": table_name,
                            "column_name": col_item.column_name,
                            "ok": True,
                        })
                    except Exception as e:
                        results.append({
                            "table_name": table_name,
                            "column_name": col_item.column_name,
                            "ok": False,
                            "error": str(e),
                        })
            conn.commit()

        return {"ok": True, "results": results}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"修改列注释失败: {e}")
