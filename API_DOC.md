# 智能问数 Agent API 文档

> **服务基址**：`http://<host>:8080`
> **Swagger UI**：`http://<host>:8080/docs`
> **版本**：1.0.0
> **Content-Type**：`application/json`（流式接口除外）

---

## 目录

1. [通用说明](#1-通用说明)
2. [问答模块](#2-问答模块)
3. [数据源管理](#3-数据源管理)
4. [知识库管理](#4-知识库管理)
5. [MCP 连接器](#5-mcp-连接器)
6. [会话管理](#6-会话管理)
7. [模型管理](#7-模型管理)
8. [AWEL Flow 管理](#8-awel-flow-管理)
9. [Prompt 管理](#9-prompt-管理)
10. [App 管理](#10-app-管理)
11. [外部平台兼容接口](#11-外部平台兼容接口)
12. [评估管理](#12-评估管理)

---

## 1. 通用说明

### 统一响应格式

**成功响应**：
```json
{
  "ok": true,
  "...其他字段": "..."
}
```

**错误响应**：
```json
{
  "detail": "错误描述信息"
}
```

### HTTP 状态码

| 状态码 | 含义 |
|--------|------|
| 200 | 请求成功 |
| 400 | 请求参数错误 / 业务逻辑失败（如连接测试失败） |
| 404 | 资源不存在 |
| 422 | 请求体校验失败（Pydantic 字段校验） |
| 502 | 网关错误（DB-GPT 后端不可达或返回异常） |

### 422 校验错误示例

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "question"],
      "msg": "Field required",
      "input": {}
    }
  ]
}
```

---

## 2. 问答模块

> v2 更新：原 4 个独立接口（`/ask`、`/ask/stream`、`/ask/knowledge`、`/ask/flow`）已合并为 **1 个统一接口**，通过 `chat_mode` + `chat_param` 参数组合覆盖所有问答场景。旧接口 `/ask/knowledge`、`/ask/flow` 保留向后兼容（已标记 deprecated）。
>
> v3 更新：新增 `/ask/react-agent` 接口，调用 DB-GPT 原生 react-agent，支持多步推理 + SQL 执行 + 结果返回，与 DB-GPT 前端体验一致。推荐数据对话场景使用此接口。

### 2.1 统一问答接口

**请求方式**：`POST`

**请求地址**：`/ask` 或 `/ask/`

**设计思路**：通过 `chat_mode` + `chat_param` 两个参数的组合，一个接口覆盖所有问答场景：

| 场景 | chat_mode | chat_param | 说明 |
|------|-----------|------------|------|
| 纯对话 | 不传 或 `chat_normal` | 不传 | 不关联任何数据源/知识库，纯 LLM 对话 |
| 数据对话（NL2SQL） | 不传 或 `chat_data` | 数据源名 | 自动推断为 chat_data，执行 SQL |
| 知识库问答 | `chat_knowledge` | 知识库名 | 基于知识库检索回答 |
| Flow 问答 | `chat_flow` | Flow UID | 走 AWEL Flow 处理 |
| App 问答 | `chat_app` | App code | 走 App Agent 处理 |
| 仪表盘 | `chat_dashboard` | 数据源名 | 生成仪表盘视图 |
| 自定义 | 用户指定 | 对应参数 | 完全由调用方控制 |

**自动推断规则**：
- 不传 `chat_mode` 且不传 `chat_param` → `chat_normal`（纯对话）
- 不传 `chat_mode` 但传了 `chat_param` → `chat_data`（数据对话）
- 传了 `chat_mode` → 直接使用指定的模式

**请求参数**：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| question | string | 是 | - | 自然语言问题 |
| chat_mode | string | 否 | null | 问答模式（不传时自动推断） |
| chat_param | string | 否 | null | 问答参数（数据源名/知识库名/Flow UID） |
| session | string | 否 | `""` | 会话 ID，缺省自动管理 |
| temperature | float | 否 | 0.2 | 温度参数 |
| max_new_tokens | int | 否 | 4000 | 最大 token 数 |
| normalize_mysql | bool | 否 | null | MySQL 归一化（null 时：chat_data=True，其他=False） |

#### 场景一：纯对话（不关联任何源）

**请求示例**：
```bash
curl -X POST http://localhost:8080/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"1+1等于几"}'
```

**正常响应**（200）：
```json
{
  "ok": true,
  "answer": "1 + 1 等于 **2**。",
  "sql": "",
  "data": null,
  "display_type": "response_table",
  "asked": true,
  "conv_uid": "a8d6740d-...",
  "error": ""
}
```

#### 场景二：数据对话（NL2SQL，显式指定）

**请求示例**：
```bash
curl -X POST http://localhost:8080/ask \
  -H "Content-Type: application/json" \
  -d '{
    "question": "列出所有书名",
    "chat_mode": "chat_data",
    "chat_param": "chase_book"
  }'
```

**正常响应**（200）：
```json
{
  "ok": true,
  "answer": "查询结果如下...",
  "sql": "SELECT `书名` FROM `图书` LIMIT 50",
  "data": [
    {"书名": "平凡的世界"},
    {"书名": "巴菲特的估值逻辑"},
    {"书名": "半小时世界漫画史"}
  ],
  "display_type": "response_table",
  "asked": false,
  "conv_uid": "e0d416a0-...",
  "error": ""
}
```

#### 场景三：数据对话（自动推断，只传 chat_param）

**请求示例**：
```bash
curl -X POST http://localhost:8080/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"列出所有书名","chat_param":"chase_book"}'
```

> 不传 `chat_mode`，系统自动推断为 `chat_data`。

**正常响应**：同场景二。

#### 场景四：知识库问答

**请求示例**：
```bash
curl -X POST http://localhost:8080/ask \
  -H "Content-Type: application/json" \
  -d '{
    "question": "公司有哪些产品",
    "chat_mode": "chat_knowledge",
    "chat_param": "product_kb"
  }'
```

**正常响应**（200）：
```json
{
  "ok": true,
  "answer": "根据知识库内容，公司有以下产品...",
  "sql": "",
  "data": null,
  "display_type": "",
  "asked": false,
  "conv_uid": "e5f6g7h8-...",
  "error": ""
}
```

#### 场景五：Flow 问答

**请求示例**：
```bash
curl -X POST http://localhost:8080/ask \
  -H "Content-Type: application/json" \
  -d '{
    "question": "分析销售趋势",
    "chat_mode": "chat_flow",
    "chat_param": "flow-abc123"
  }'
```

**正常响应**（200）：
```json
{
  "ok": true,
  "answer": "根据 Flow 处理结果...",
  "sql": "",
  "data": null,
  "display_type": "",
  "asked": false,
  "conv_uid": "i9j0k1l2-...",
  "error": ""
}
```

**错误响应**（502）：
```json
{
  "detail": "调用 DB-GPT 异常: Connection refused"
}
```

---

### 2.2 统一流式问答接口（SSE）

**请求方式**：`POST`

**请求地址**：`/ask/stream`

**请求参数**：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| question | string | 是 | - | 自然语言问题 |
| chat_mode | string | 否 | null | 问答模式（自动推断） |
| chat_param | string | 否 | null | 问答参数（数据源名/知识库名/Flow UID） |
| session | string | 否 | `""` | 会话 ID |
| temperature | float | 否 | 0.2 | 温度参数 |
| max_new_tokens | int | 否 | 4000 | 最大 token 数 |

**请求示例**（纯对话流式）：
```bash
curl -N http://localhost:8080/ask/stream \
  -H "Content-Type: application/json" \
  -d '{"question":"你好"}'
```

**请求示例**（数据对话流式）：
```bash
curl -N http://localhost:8080/ask/stream \
  -H "Content-Type: application/json" \
  -d '{"question":"按评分排序","chat_param":"chase_book"}'
```

**正常响应**（200，`text/event-stream`）：
```
data: 根据

data: 您的要求

data: [DONE]
```

**错误响应**（502）：
```json
{
  "detail": "调用 DB-GPT 异常: ..."
}
```

---

### 2.3 React Agent 智能问答（SSE）

**请求方式**：`POST`

**请求地址**：`/ask/react-agent`

**说明**：调用 DB-GPT 原生 react-agent，支持多步推理 + SQL 执行 + 结果返回。与 DB-GPT 前端使用的接口一致，能实际执行 SQL 并返回结果数据。推荐用于数据对话场景。

**请求参数**：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| question | string | 是 | - | 自然语言问题 |
| chat_param | string | 否 | - | 数据源名（如 chase_double11），不传则纯对话 |
| session | string | 否 | `""` | 会话 ID |
| temperature | float | 否 | 0.6 | 温度参数 |
| max_new_tokens | int | 否 | 4000 | 最大 token 数 |

**请求示例**：
```bash
curl -N -X POST http://localhost:8080/ask/react-agent \
  -H "Content-Type: application/json" \
  -d '{"question":"双十一有几个活动","chat_param":"chase_double11"}'
```

**正常响应**（200，`text/event-stream`，逐行 SSE 事件）：
```
data: {"type": "context.status", "used": 4736, "budget": 115904, "ratio": 0.04}

data: {"type": "step.start", "step": 1, "id": "step-1", "title": "思考中"}

data: {"type": "step.meta", "id": "step-1", "thought": "查询活动数量", "action": "sql_query", "action_input": "{\"sql\": \"SELECT COUNT(*) FROM ...\"}"}

data: {"type": "step.chunk", "id": "step-1", "output_type": "markdown", "content": "| 活动数量 |\n| --- |\n| 1 |"}

data: {"type": "step.done", "id": "step-1", "status": "done"}

data: {"type": "final", "protocol_version": 2, "content": "双十一有1个活动。", "citations": []}

data: {"type": "done"}
```

**SSE 事件类型**：

| type | 说明 |
|------|------|
| `context.status` | 上下文预算信息 |
| `step.start` | 推理步骤开始 |
| `step.meta` | 步骤元信息（thought / action / action_input） |
| `step.chunk` | 步骤输出内容（markdown 表格/文本） |
| `step.done` | 步骤完成 |
| `final` | 最终自然语言回答 |
| `done` | 流结束 |
| `error` | 错误 |

**错误响应**（200 + error 事件）：
```
data: {"type": "error", "message": "DB-GPT 500: ..."}
```

---

### 2.4 查看支持的问答模式

**请求方式**：`GET`

**请求地址**：`/ask/chat-modes`

**请求参数**：无

**请求示例**：
```bash
curl http://localhost:8080/ask/chat-modes
```

**正常响应**（200）：
```json
{
  "ok": true,
  "modes": [
    {"value": "chat_normal", "name": "NORMAL"},
    {"value": "chat_data", "name": "DATA"},
    {"value": "chat_knowledge", "name": "KNOWLEDGE"},
    {"value": "chat_flow", "name": "FLOW"},
    {"value": "chat_app", "name": "APP"},
    {"value": "chat_with_db_qa", "name": "DB_QA"},
    {"value": "chat_dashboard", "name": "DASHBOARD"}
  ]
}
```

---

### 2.5 新建会话

**请求方式**：`POST`

**请求地址**：`/ask/session/new`

**请求参数**：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| key | string | 是 | - | 会话标识（数据源名或自定义 key） |

**请求示例**：
```bash
curl -X POST http://localhost:8080/ask/session/new \
  -H "Content-Type: application/json" \
  -d '{"key":"chase_book"}'
```

**正常响应**（200）：
```json
{
  "ok": true,
  "key": "chase_book",
  "session": "m3n4o5p6-..."
}
```

---

### 2.6 列出所有会话

**请求方式**：`GET`

**请求地址**：`/ask/sessions`

**请求参数**：无

**请求示例**：
```bash
curl http://localhost:8080/ask/sessions
```

**正常响应**（200）：
```json
{
  "ok": true,
  "sessions": {
    "chase_book": "a1b2c3d4-...",
    "chase_tv": "e5f6g7h8-...",
    "default": "a8d6740d-..."
  }
}
```

---

### 2.7 移除会话

**请求方式**：`DELETE`

**请求地址**：`/ask/sessions/{key}`

**路径参数**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| key | string | 是 | 会话标识 |

**请求示例**：
```bash
curl -X DELETE http://localhost:8080/ask/sessions/chase_book
```

**正常响应**（200）：
```json
{
  "ok": true,
  "removed": "chase_book"
}
```

---

### 2.8 清空所有会话

**请求方式**：`POST`

**请求地址**：`/ask/sessions/reset`

**请求参数**：无

**请求示例**：
```bash
curl -X POST http://localhost:8080/ask/sessions/reset
```

**正常响应**（200）：
```json
{
  "ok": true,
  "cleared": true
}
```

---

### 2.9 [已废弃] 知识库问答旧接口

> **已废弃**：请使用 `POST /ask`，传 `chat_mode=chat_knowledge` + `chat_param=知识库名`。

**请求方式**：`POST`

**请求地址**：`/ask/knowledge`

**请求参数**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| question | string | 是 | 自然语言问题 |
| space_name | string | 是 | 知识库名称 |
| session | string | 否 | 会话 ID |
| temperature | float | 否 | 温度参数 |
| max_new_tokens | int | 否 | 最大 token 数 |

---

### 2.10 [已废弃] Flow 问答旧接口

> **已废弃**：请使用 `POST /ask`，传 `chat_mode=chat_flow` + `chat_param=Flow UID`。

**请求方式**：`POST`

**请求地址**：`/ask/flow`

**请求参数**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| question | string | 是 | 自然语言问题 |
| flow_uid | string | 是 | Flow UID |
| session | string | 否 | 会话 ID |
| temperature | float | 否 | 温度参数 |
| max_new_tokens | int | 否 | 最大 token 数 |

---

## 3. 数据源管理

### 3.1 列出所有数据源

**请求方式**：`GET`

**请求地址**：`/datasources` 或 `/datasources/`

**请求参数**：无

**请求示例**：
```bash
curl http://localhost:8080/datasources
```

**正常响应**（200）：
```json
{
  "ok": true,
  "datasources": [
    {
      "id": "1",
      "db_type": "mysql",
      "db_name": "chase_book",
      "db_host": "10.12.61.23",
      "db_port": 3299,
      "db_path": "",
      "db_user": "root1",
      "comment": "CHASE 图书数据库"
    }
  ]
}
```

**错误响应**（502）：
```json
{
  "detail": "获取数据源列表失败: ..."
}
```

---

### 3.2 获取数据源详情

**请求方式**：`GET`

**请求地址**：`/datasources/{datasource_id}`

**路径参数**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| datasource_id | string | 是 | 数据源 ID |

**请求示例**：
```bash
curl http://localhost:8080/datasources/1
```

**正常响应**（200）：
```json
{
  "ok": true,
  "datasource": {
    "id": "1",
    "db_type": "mysql",
    "db_name": "chase_book",
    "db_path": "",
    "db_host": "10.12.61.23",
    "db_port": 3299,
    "db_user": "root1",
    "comment": "CHASE 图书数据库"
  }
}
```

**错误响应**（404）：
```json
{
  "detail": "..."
}
```

---

### 3.3 新建数据源

**请求方式**：`POST`

**请求地址**：`/datasources` 或 `/datasources/`

**请求参数**：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| db_type | string | 是 | - | 数据库类型：sqlite / mysql / duckdb 等 |
| db_name | string | 是 | - | 数据库名 |
| db_path | string | 否 | `""` | 文件型数据库路径（sqlite 用） |
| db_host | string | 否 | `""` | 数据库主机地址 |
| db_port | int | 否 | 0 | 数据库端口 |
| db_user | string | 否 | `""` | 数据库用户名 |
| db_pwd | string | 否 | `""` | 数据库密码 |
| comment | string | 否 | `""` | 备注说明 |

**请求示例**：
```bash
curl -X POST http://localhost:8080/datasources \
  -H "Content-Type: application/json" \
  -d '{
    "db_type": "mysql",
    "db_name": "chase_book",
    "db_host": "10.12.61.23",
    "db_port": 3299,
    "db_user": "root1",
    "db_pwd": "Wlw123456!",
    "comment": "CHASE 图书数据库"
  }'
```

**正常响应**（200）：
```json
{
  "ok": true,
  "datasource": {
    "id": "2",
    "db_type": "mysql",
    "db_name": "chase_book",
    "comment": "CHASE 图书数据库"
  }
}
```

**错误响应**（502）：
```json
{
  "detail": "创建数据源失败: ..."
}
```

---

### 3.4 更新数据源

**请求方式**：`PUT`

**请求地址**：`/datasources` 或 `/datasources/`

**请求参数**：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| id | int | 是 | - | 数据源 ID |
| db_type | string | 是 | - | 数据库类型 |
| db_name | string | 是 | - | 数据库名 |
| db_path | string | 否 | `""` | 文件路径 |
| db_host | string | 否 | `""` | 主机地址 |
| db_port | int | 否 | 0 | 端口 |
| db_user | string | 否 | `""` | 用户名 |
| db_pwd | string | 否 | `""` | 密码 |
| comment | string | 否 | `""` | 备注 |

**请求示例**：
```bash
curl -X PUT http://localhost:8080/datasources \
  -H "Content-Type: application/json" \
  -d '{
    "id": 2,
    "db_type": "mysql",
    "db_name": "chase_book",
    "db_host": "10.12.61.23",
    "db_port": 3299,
    "db_user": "root1",
    "db_pwd": "new_password",
    "comment": "更新后的备注"
  }'
```

**正常响应**（200）：
```json
{
  "ok": true,
  "datasource": {
    "id": "2",
    "db_type": "mysql",
    "db_name": "chase_book",
    "comment": "更新后的备注"
  }
}
```

**错误响应**（502）：
```json
{
  "detail": "更新数据源失败: ..."
}
```

---

### 3.5 删除数据源

**请求方式**：`DELETE`

**请求地址**：`/datasources/{datasource_id}`

**路径参数**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| datasource_id | string | 是 | 数据源 ID |

**请求示例**：
```bash
curl -X DELETE http://localhost:8080/datasources/2
```

**正常响应**（200）：
```json
{
  "ok": true,
  "datasource": {
    "id": "2",
    "db_type": "mysql",
    "db_name": "chase_book"
  }
}
```

**错误响应**（502）：
```json
{
  "detail": "删除数据源失败: ..."
}
```

---

### 3.6 查看支持的数据源类型

**请求方式**：`GET`

**请求地址**：`/datasources/types/list`

**请求参数**：无

**请求示例**：
```bash
curl http://localhost:8080/datasources/types/list
```

**正常响应**（200）：
```json
{
  "ok": true,
  "types": [
    {"db_type": "mysql", "label": "MySQL"},
    {"db_type": "sqlite", "label": "SQLite"},
    {"db_type": "duckdb", "label": "DuckDB"}
  ]
}
```

**错误响应**（502）：
```json
{
  "detail": "获取数据源类型失败: ..."
}
```

---

### 3.7 测试数据库连接

**请求方式**：`POST`

**请求地址**：`/datasources/test-connection`

**请求参数**：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| db_type | string | 是 | - | 数据库类型 |
| db_name | string | 是 | - | 数据库名 |
| db_path | string | 否 | `""` | 文件路径 |
| db_host | string | 否 | `""` | 主机地址 |
| db_port | int | 否 | 0 | 端口 |
| db_user | string | 否 | `""` | 用户名 |
| db_pwd | string | 否 | `""` | 密码 |

**请求示例**：
```bash
curl -X POST http://localhost:8080/datasources/test-connection \
  -H "Content-Type: application/json" \
  -d '{
    "db_type": "mysql",
    "db_name": "chase_book",
    "db_host": "10.12.61.23",
    "db_port": 3299,
    "db_user": "root1",
    "db_pwd": "Wlw123456!"
  }'
```

**正常响应**（200）：
```json
{
  "ok": true,
  "connected": true
}
```

**错误响应**（400）：
```json
{
  "detail": "..."
}
```

---

### 3.8 刷新数据源元信息

**请求方式**：`POST`

**请求地址**：`/datasources/{datasource_id}/refresh`

**路径参数**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| datasource_id | string | 是 | 数据源 ID |

**请求示例**：
```bash
curl -X POST http://localhost:8080/datasources/1/refresh
```

**正常响应**（200）：
```json
{
  "ok": true,
  "refreshed": true
}
```

**错误响应**（400）：
```json
{
  "detail": "..."
}
```

---

## 4. 知识库管理

### 4.1 列出所有知识空间

**请求方式**：`GET`

**请求地址**：`/knowledge/spaces` 或 `/knowledge/spaces/`

**请求参数**：无

**请求示例**：
```bash
curl http://localhost:8080/knowledge/spaces
```

**正常响应**（200）：
```json
{
  "ok": true,
  "spaces": [
    {
      "id": "1",
      "name": "product_kb",
      "vector_type": "Chroma",
      "desc": "产品知识库",
      "owner": "admin",
      "context": null
    }
  ]
}
```

**错误响应**（502）：
```json
{
  "detail": "获取知识空间列表失败: ..."
}
```

---

### 4.2 获取知识空间详情

**请求方式**：`GET`

**请求地址**：`/knowledge/spaces/{space_id}`

**路径参数**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| space_id | string | 是 | 空间 ID |

**请求示例**：
```bash
curl http://localhost:8080/knowledge/spaces/1
```

**正常响应**（200）：
```json
{
  "ok": true,
  "space": {
    "id": "1",
    "name": "product_kb",
    "vector_type": "Chroma",
    "desc": "产品知识库",
    "owner": "admin",
    "context": null
  }
}
```

**错误响应**（404）：
```json
{
  "detail": "..."
}
```

---

### 4.3 创建知识空间

**请求方式**：`POST`

**请求地址**：`/knowledge/spaces` 或 `/knowledge/spaces/`

**请求参数**：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| name | string | 是 | - | 知识空间名称 |
| vector_type | string | 否 | `""` | 向量类型 |
| desc | string | 否 | `""` | 描述 |
| owner | string | 否 | `""` | 所有者 |
| context | string | 否 | null | 空间参数上下文 |

**请求示例**：
```bash
curl -X POST http://localhost:8080/knowledge/spaces \
  -H "Content-Type: application/json" \
  -d '{"name":"product_kb","vector_type":"Chroma","desc":"产品知识库","owner":"admin"}'
```

**正常响应**（200）：
```json
{
  "ok": true,
  "space": {
    "id": "2",
    "name": "product_kb",
    "vector_type": "Chroma",
    "desc": "产品知识库"
  }
}
```

**错误响应**（502）：
```json
{
  "detail": "创建知识空间失败: ..."
}
```

---

### 4.4 更新知识空间

**请求方式**：`PUT`

**请求地址**：`/knowledge/spaces` 或 `/knowledge/spaces/`

**请求参数**：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| id | int | 是 | - | 空间 ID |
| name | string | 否 | `""` | 名称 |
| vector_type | string | 否 | `""` | 向量类型 |
| desc | string | 否 | `""` | 描述 |
| owner | string | 否 | `""` | 所有者 |
| context | string | 否 | null | 上下文 |

**请求示例**：
```bash
curl -X PUT http://localhost:8080/knowledge/spaces \
  -H "Content-Type: application/json" \
  -d '{"id":2,"name":"product_kb_v2","desc":"更新后的描述"}'
```

**正常响应**（200）：
```json
{
  "ok": true,
  "space": {
    "id": "2",
    "name": "product_kb_v2",
    "desc": "更新后的描述"
  }
}
```

**错误响应**（502）：
```json
{
  "detail": "更新知识空间失败: ..."
}
```

---

### 4.5 删除知识空间

**请求方式**：`DELETE`

**请求地址**：`/knowledge/spaces/{space_id}`

**路径参数**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| space_id | string | 是 | 空间 ID |

**请求示例**：
```bash
curl -X DELETE http://localhost:8080/knowledge/spaces/2
```

**正常响应**（200）：
```json
{
  "ok": true,
  "space": {
    "id": "2",
    "name": "product_kb_v2"
  }
}
```

**错误响应**（502）：
```json
{
  "detail": "删除知识空间失败: ..."
}
```

---

### 4.6 列出所有文档

**请求方式**：`GET`

**请求地址**：`/knowledge/documents` 或 `/knowledge/documents/`

**请求参数**：无

**请求示例**：
```bash
curl http://localhost:8080/knowledge/documents
```

**正常响应**（200）：
```json
{
  "ok": true,
  "documents": [
    {
      "id": "1",
      "doc_name": "产品手册",
      "doc_type": "document",
      "content": "第一章 产品概述...",
      "doc_source": "",
      "space_id": "1"
    }
  ]
}
```

**错误响应**（502）：
```json
{
  "detail": "获取文档列表失败: ..."
}
```

---

### 4.7 获取文档详情

**请求方式**：`GET`

**请求地址**：`/knowledge/documents/{document_id}`

**路径参数**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| document_id | string | 是 | 文档 ID |

**请求示例**：
```bash
curl http://localhost:8080/knowledge/documents/1
```

**正常响应**（200）：
```json
{
  "ok": true,
  "document": {
    "id": "1",
    "doc_name": "产品手册",
    "doc_type": "document",
    "content": "第一章 产品概述\n产品 A 是...",
    "doc_source": "",
    "space_id": "1"
  }
}
```

**错误响应**（404）：
```json
{
  "detail": "..."
}
```

---

### 4.8 创建文档

**请求方式**：`POST`

**请求地址**：`/knowledge/documents` 或 `/knowledge/documents/`

**请求参数**：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| doc_name | string | 是 | - | 文档名称 |
| doc_type | string | 否 | `document` | 文档类型 |
| content | string | 否 | `""` | 文档内容 |
| doc_source | string | 否 | `""` | 文档来源 |
| space_id | string | 否 | `""` | 空间 ID |

**请求示例**：
```bash
curl -X POST http://localhost:8080/knowledge/documents \
  -H "Content-Type: application/json" \
  -d '{
    "doc_name": "产品手册",
    "doc_type": "document",
    "content": "第一章 产品概述\n产品 A 是...",
    "space_id": "1"
  }'
```

**正常响应**（200）：
```json
{
  "ok": true,
  "document": {
    "id": "2",
    "doc_name": "产品手册",
    "doc_type": "document"
  }
}
```

**错误响应**（502）：
```json
{
  "detail": "创建文档失败: ..."
}
```

---

### 4.9 删除文档

**请求方式**：`DELETE`

**请求地址**：`/knowledge/documents/{document_id}`

**路径参数**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| document_id | string | 是 | 文档 ID |

**请求示例**：
```bash
curl -X DELETE http://localhost:8080/knowledge/documents/2
```

**正常响应**（200）：
```json
{
  "ok": true,
  "document": {
    "id": "2",
    "doc_name": "产品手册"
  }
}
```

**错误响应**（502）：
```json
{
  "detail": "删除文档失败: ..."
}
```

---

### 4.10 同步文档

**请求方式**：`POST`

**请求地址**：`/knowledge/documents/sync` 或 `/knowledge/documents/sync/`

**请求参数**：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| doc_id | string | 是 | - | 文档 ID |
| space_id | string | 否 | `""` | 空间 ID |
| model_name | string | 否 | null | 模型名称 |

**请求示例**：
```bash
curl -X POST http://localhost:8080/knowledge/documents/sync \
  -H "Content-Type: application/json" \
  -d '{"doc_id":"2","space_id":"1","model_name":"TS-MOMA/DeepSeek-V4-Flash"}'
```

**正常响应**（200）：
```json
{
  "ok": true,
  "synced_doc_ids": "2"
}
```

**错误响应**（502）：
```json
{
  "detail": "同步文档失败: ..."
}
```

---

### 4.11 知识库检索

**请求方式**：`POST`

**请求地址**：`/knowledge/spaces/{space_id}/retrieve`

**路径参数**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| space_id | int | 是 | 空间 ID |

**请求参数**（Body）：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| query | string | 是 | - | 检索问题 |
| top_k | int | 否 | 5 | 返回 Top K |
| score_threshold | float | 否 | 0.3 | 相似度阈值 |

**请求示例**：
```bash
curl -X POST http://localhost:8080/knowledge/spaces/1/retrieve \
  -H "Content-Type: application/json" \
  -d '{"query":"产品A有哪些功能","top_k":5,"score_threshold":0.3}'
```

**正常响应**（200）：
```json
{
  "ok": true,
  "results": [
    {
      "content": "产品 A 功能包括...",
      "score": 0.85,
      "metadata": {"source": "产品手册"}
    }
  ]
}
```

**错误响应**（400）：
```json
{
  "detail": "..."
}
```

---

## 5. MCP 连接器

### 5.1 列出连接器类型

**请求方式**：`GET`

**请求地址**：`/connectors/types`

**请求参数**：无

**请求示例**：
```bash
curl http://localhost:8080/connectors/types
```

**正常响应**（200）：
```json
{
  "ok": true,
  "types": [
    {"type": "custom_mcp", "label": "Custom MCP"},
    {"type": "mcp_server", "label": "MCP Server"}
  ]
}
```

**错误响应**（502）：
```json
{
  "detail": "获取连接器类型失败: ..."
}
```

---

### 5.2 列出所有连接器

**请求方式**：`GET`

**请求地址**：`/connectors` 或 `/connectors/`

**Query 参数**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| user_name | string | 否 | 用户名 |
| sys_code | string | 否 | 系统编码 |

**请求示例**：
```bash
curl "http://localhost:8080/connectors?user_name=admin"
```

**正常响应**（200）：
```json
{
  "ok": true,
  "connectors": [
    {
      "id": "1",
      "type": "custom_mcp",
      "name": "my_mcp_connector",
      "config": {}
    }
  ]
}
```

**错误响应**（502）：
```json
{
  "detail": "获取连接器列表失败: ..."
}
```

---

### 5.3 获取连接器详情

**请求方式**：`GET`

**请求地址**：`/connectors/{connector_id}`

**路径参数**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| connector_id | string | 是 | 连接器 ID |

**请求示例**：
```bash
curl http://localhost:8080/connectors/1
```

**正常响应**（200）：
```json
{
  "ok": true,
  "connector": {
    "id": "1",
    "type": "custom_mcp",
    "name": "my_mcp_connector",
    "config": {}
  }
}
```

**错误响应**（404）：
```json
{
  "detail": "..."
}
```

---

### 5.4 创建连接器

**请求方式**：`POST`

**请求地址**：`/connectors` 或 `/connectors/`

**请求参数**：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| type | string | 是 | - | 连接器类型，如 custom_mcp |
| name | string | 是 | - | 连接器名称 |
| config | object | 否 | `{}` | 配置参数 |
| user_name | string | 否 | null | 用户名 |
| sys_code | string | 否 | null | 系统编码 |

**请求示例**：
```bash
curl -X POST http://localhost:8080/connectors \
  -H "Content-Type: application/json" \
  -d '{
    "type": "custom_mcp",
    "name": "my_mcp_connector",
    "config": {"url": "http://localhost:9000"},
    "user_name": "admin"
  }'
```

**正常响应**（200）：
```json
{
  "ok": true,
  "connector": {
    "id": "2",
    "type": "custom_mcp",
    "name": "my_mcp_connector",
    "config": {"url": "http://localhost:9000"}
  }
}
```

**错误响应**（400）：
```json
{
  "detail": "..."
}
```

---

### 5.5 更新连接器

**请求方式**：`PUT`

**请求地址**：`/connectors/{connector_id}`

**路径参数**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| connector_id | string | 是 | 连接器 ID |

**请求参数**：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| type | string | 否 | null | 连接器类型 |
| name | string | 否 | null | 连接器名称 |
| config | object | 否 | null | 配置参数 |
| user_name | string | 否 | null | 用户名 |
| sys_code | string | 否 | null | 系统编码 |

**请求示例**：
```bash
curl -X PUT http://localhost:8080/connectors/2 \
  -H "Content-Type: application/json" \
  -d '{"name":"updated_connector"}'
```

**正常响应**（200）：
```json
{
  "ok": true,
  "connector": {
    "id": "2",
    "type": "custom_mcp",
    "name": "updated_connector",
    "config": {"url": "http://localhost:9000"}
  }
}
```

**错误响应**（400）：
```json
{
  "detail": "..."
}
```

---

### 5.6 删除连接器

**请求方式**：`DELETE`

**请求地址**：`/connectors/{connector_id}`

**路径参数**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| connector_id | string | 是 | 连接器 ID |

**请求示例**：
```bash
curl -X DELETE http://localhost:8080/connectors/2
```

**正常响应**（200）：
```json
{
  "ok": true,
  "deleted": true
}
```

**错误响应**（400）：
```json
{
  "detail": "..."
}
```

---

### 5.7 测试连接器连通性

**请求方式**：`POST`

**请求地址**：`/connectors/{connector_id}/test`

**路径参数**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| connector_id | string | 是 | 连接器 ID |

**请求示例**：
```bash
curl -X POST http://localhost:8080/connectors/1/test
```

**正常响应**（200）：
```json
{
  "ok": true,
  "result": true
}
```

**错误响应**（400）：
```json
{
  "detail": "..."
}
```

---

### 5.8 获取连接器工具列表

**请求方式**：`GET`

**请求地址**：`/connectors/{connector_id}/tools`

**路径参数**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| connector_id | string | 是 | 连接器 ID |

**请求示例**：
```bash
curl http://localhost:8080/connectors/1/tools
```

**正常响应**（200）：
```json
{
  "ok": true,
  "tools": [
    {"name": "search", "description": "搜索工具"},
    {"name": "fetch", "description": "抓取工具"}
  ]
}
```

**错误响应**（404）：
```json
{
  "detail": "..."
}
```

---

### 5.9 列出待确认操作

**请求方式**：`GET`

**请求地址**：`/connectors/pending-confirms`

**请求参数**：无

**请求示例**：
```bash
curl http://localhost:8080/connectors/pending-confirms
```

**正常响应**（200）：
```json
{
  "ok": true,
  "confirms": [
    {
      "confirm_id": "abc123",
      "action": "execute_tool",
      "description": "执行搜索工具"
    }
  ]
}
```

**错误响应**（502）：
```json
{
  "detail": "获取待确认列表失败: ..."
}
```

---

### 5.10 确认/拒绝待确认操作

**请求方式**：`POST`

**请求地址**：`/connectors/confirm`

**请求参数**：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| confirm_id | string | 是 | - | 确认 ID |
| approved | bool | 是 | - | 是否批准 |
| reason | string | 否 | null | 理由 |

**请求示例**：
```bash
curl -X POST http://localhost:8080/connectors/confirm \
  -H "Content-Type: application/json" \
  -d '{"confirm_id":"abc123","approved":true,"reason":"用户确认执行"}'
```

**正常响应**（200）：
```json
{
  "ok": true,
  "result": {
    "success": true,
    "message": "操作已确认"
  }
}
```

**错误响应**（502）：
```json
{
  "detail": "确认操作失败: ..."
}
```

---

## 6. 会话管理

### 6.1 新建会话

**请求方式**：`POST`

**请求地址**：`/conversations/new`

**请求参数**：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| user_name | string | 否 | null | 用户名 |
| sys_code | string | 否 | null | 系统编码 |

**请求示例**：
```bash
curl -X POST http://localhost:8080/conversations/new \
  -H "Content-Type: application/json" \
  -d '{"user_name":"admin"}'
```

**正常响应**（200）：
```json
{
  "ok": true,
  "conversation": {
    "conv_uid": "a1b2c3d4-e5f6-...",
    "user_name": "admin",
    "user_input": "",
    "ai_message": ""
  }
}
```

**错误响应**（502）：
```json
{
  "detail": "新建会话失败: ..."
}
```

---

### 6.2 列出会话

**请求方式**：`GET`

**请求地址**：`/conversations/list`

**Query 参数**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| user_name | string | 否 | 用户名 |
| sys_code | string | 否 | 系统编码 |

**请求示例**：
```bash
curl "http://localhost:8080/conversations/list?user_name=admin"
```

**正常响应**（200）：
```json
{
  "ok": true,
  "conversations": [
    {
      "conv_uid": "a1b2c3d4-...",
      "title": "关于图书数据的对话",
      "user_name": "admin"
    }
  ]
}
```

**错误响应**（502）：
```json
{
  "detail": "获取会话列表失败: ..."
}
```

---

### 6.3 删除会话

**请求方式**：`POST`

**请求地址**：`/conversations/delete`

**请求参数**：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| con_uid | string | 是 | - | 会话 UID |

**请求示例**：
```bash
curl -X POST http://localhost:8080/conversations/delete \
  -H "Content-Type: application/json" \
  -d '{"con_uid":"a1b2c3d4-..."}'
```

**正常响应**（200）：
```json
{
  "ok": true,
  "deleted": "a1b2c3d4-..."
}
```

**错误响应**（502）：
```json
{
  "detail": "删除会话失败: ..."
}
```

---

### 6.4 清空用户所有会话

**请求方式**：`POST`

**请求地址**：`/conversations/clear`

**请求参数**：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| user_name | string | 否 | null | 用户名 |
| sys_code | string | 否 | null | 系统编码 |

**请求示例**：
```bash
curl -X POST http://localhost:8080/conversations/clear \
  -H "Content-Type: application/json" \
  -d '{"user_name":"admin"}'
```

**正常响应**（200）：
```json
{
  "ok": true,
  "cleared": true
}
```

**错误响应**（502）：
```json
{
  "detail": "清空会话失败: ..."
}
```

---

### 6.5 获取会话历史消息

**请求方式**：`GET`

**请求地址**：`/conversations/messages/history`

**Query 参数**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| con_uid | string | 是 | 会话 UID |

**请求示例**：
```bash
curl "http://localhost:8080/conversations/messages/history?con_uid=a1b2c3d4-..."
```

**正常响应**（200）：
```json
{
  "ok": true,
  "messages": [
    {
      "role": "human",
      "content": "列出所有书名",
      "time_stamp": "2026-09-04T10:00:00"
    },
    {
      "role": "ai",
      "content": "查询结果：三体、活着、百年孤独...",
      "time_stamp": "2026-09-04T10:00:05"
    }
  ]
}
```

**错误响应**（502）：
```json
{
  "detail": "获取历史消息失败: ..."
}
```

---

### 6.6 分页查询会话

**请求方式**：`POST`

**请求地址**：`/conversations/query_page`

**请求参数**：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| user_name | string | 否 | null | 用户名 |
| sys_code | string | 否 | null | 系统编码 |
| page | int | 否 | 1 | 页码 |
| page_size | int | 否 | 20 | 每页条数 |

**请求示例**：
```bash
curl -X POST http://localhost:8080/conversations/query_page \
  -H "Content-Type: application/json" \
  -d '{"user_name":"admin","page":1,"page_size":10}'
```

**正常响应**（200）：
```json
{
  "ok": true,
  "page": {
    "items": [
      {"conv_uid": "a1b2c3d4-...", "title": "对话1"},
      {"conv_uid": "e5f6g7h8-...", "title": "对话2"}
    ],
    "total": 25,
    "page": 1,
    "page_size": 10
  }
}
```

**错误响应**（502）：
```json
{
  "detail": "分页查询会话失败: ..."
}
```

---

## 7. 模型管理

### 7.1 列出支持的模型类型

**请求方式**：`GET`

**请求地址**：`/models/model-types`

**请求参数**：无

**请求示例**：
```bash
curl http://localhost:8080/models/model-types
```

**正常响应**（200）：
```json
{
  "ok": true,
  "model_types": [
    {"model_type": "llm", "label": "大语言模型"},
    {"model_type": "embedding", "label": "嵌入模型"},
    {"model_type": "rerank", "label": "重排序模型"}
  ]
}
```

**错误响应**（502）：
```json
{
  "detail": "获取模型类型失败: ..."
}
```

---

### 7.2 列出所有运行中的模型

**请求方式**：`GET`

**请求地址**：`/models/list` 或 `/models/`

**请求参数**：无

**请求示例**：
```bash
curl http://localhost:8080/models/list
```

**正常响应**（200）：
```json
{
  "ok": true,
  "models": [
    {
      "model_name": "TS-MOMA/DeepSeek-V4-Flash",
      "model_type": "llm",
      "host": "localhost",
      "port": 5670,
      "healthy": true
    }
  ]
}
```

**错误响应**（502）：
```json
{
  "detail": "获取模型列表失败: ..."
}
```

---

### 7.3 启动模型

**请求方式**：`POST`

**请求地址**：`/models/start`

**请求参数**：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| model_name | string | 是 | - | 模型名称 |
| model_type | string | 是 | - | 模型类型 |
| host | string | 否 | null | 主机 |
| port | int | 否 | null | 端口 |
| worker_type | string | 否 | null | Worker 类型 |
| params | object | 否 | null | 额外参数 |

**请求示例**：
```bash
curl -X POST http://localhost:8080/models/start \
  -H "Content-Type: application/json" \
  -d '{"model_name":"TS-MOMA/DeepSeek-V4-Flash","model_type":"llm"}'
```

**正常响应**（200）：
```json
{
  "ok": true,
  "result": true
}
```

**错误响应**（400）：
```json
{
  "detail": "..."
}
```

---

### 7.4 停止模型

**请求方式**：`POST`

**请求地址**：`/models/stop`

**请求参数**：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| model_name | string | 是 | - | 模型名称 |
| model_type | string | 是 | - | 模型类型 |
| host | string | 否 | null | 主机 |
| port | int | 否 | null | 端口 |
| worker_type | string | 否 | null | Worker 类型 |
| params | object | 否 | null | 额外参数 |

**请求示例**：
```bash
curl -X POST http://localhost:8080/models/stop \
  -H "Content-Type: application/json" \
  -d '{"model_name":"TS-MOMA/DeepSeek-V4-Flash","model_type":"llm"}'
```

**正常响应**（200）：
```json
{
  "ok": true,
  "result": true
}
```

**错误响应**（400）：
```json
{
  "detail": "..."
}
```

---

## 8. AWEL Flow 管理

### 8.1 列出所有 Flow

**请求方式**：`GET`

**请求地址**：`/flows` 或 `/flows/`

**Query 参数**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | 否 | 按名称过滤 |
| uid | string | 否 | 按 UID 过滤 |

**请求示例**：
```bash
curl http://localhost:8080/flows
```

**正常响应**（200）：
```json
{
  "ok": true,
  "flows": [
    {
      "uid": "flow-abc123",
      "name": "data_analysis_flow",
      "label": "数据分析",
      "version": "1.0",
      "description": "数据分析流程",
      "state": "running",
      "editable": true
    }
  ]
}
```

**错误响应**（502）：
```json
{
  "detail": "获取 Flow 列表失败: ..."
}
```

---

### 8.2 获取 Flow 详情

**请求方式**：`GET`

**请求地址**：`/flows/{flow_id}`

**路径参数**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| flow_id | string | 是 | Flow UID |

**请求示例**：
```bash
curl http://localhost:8080/flows/flow-abc123
```

**正常响应**（200）：
```json
{
  "ok": true,
  "flow": {
    "uid": "flow-abc123",
    "name": "data_analysis_flow",
    "label": "数据分析",
    "version": "1.0",
    "description": "数据分析流程",
    "state": "running",
    "editable": true
  }
}
```

**错误响应**（502）：
```json
{
  "detail": "获取 Flow 失败: ..."
}
```

---

### 8.3 创建 Flow

**请求方式**：`POST`

**请求地址**：`/flows` 或 `/flows/`

**请求参数**：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| name | string | 是 | - | Flow 名称 |
| label | string | 否 | null | 标签 |
| description | string | 否 | null | 描述 |
| flow_data | object | 否 | `{}` | Flow 图数据（DAG 结构） |

**请求示例**：
```bash
curl -X POST http://localhost:8080/flows \
  -H "Content-Type: application/json" \
  -d '{
    "name": "data_analysis_flow",
    "label": "数据分析",
    "description": "数据分析流程",
    "flow_data": {}
  }'
```

**正常响应**（200）：
```json
{
  "ok": true,
  "flow": {
    "uid": "flow-new456",
    "name": "data_analysis_flow",
    "label": "数据分析",
    "description": "数据分析流程"
  }
}
```

**错误响应**（502）：
```json
{
  "detail": "创建 Flow 失败: ..."
}
```

---

### 8.4 更新 Flow

**请求方式**：`PUT`

**请求地址**：`/flows/{flow_uid}`

**路径参数**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| flow_uid | string | 是 | Flow UID |

**请求参数**：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| name | string | 是 | - | Flow 名称 |
| label | string | 否 | null | 标签 |
| description | string | 否 | null | 描述 |
| flow_data | object | 否 | `{}` | Flow 图数据 |

**请求示例**：
```bash
curl -X PUT http://localhost:8080/flows/flow-new456 \
  -H "Content-Type: application/json" \
  -d '{"name":"updated_flow","label":"更新标签"}'
```

**正常响应**（200）：
```json
{
  "ok": true,
  "flow": {
    "uid": "flow-new456",
    "name": "updated_flow",
    "label": "更新标签",
    "description": null
  }
}
```

**错误响应**（502）：
```json
{
  "detail": "更新 Flow 失败: ..."
}
```

---

### 8.5 删除 Flow

**请求方式**：`DELETE`

**请求地址**：`/flows/{flow_id}`

**路径参数**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| flow_id | string | 是 | Flow UID |

**请求示例**：
```bash
curl -X DELETE http://localhost:8080/flows/flow-new456
```

**正常响应**（200）：
```json
{
  "ok": true,
  "flow": {
    "uid": "flow-new456",
    "name": "updated_flow"
  }
}
```

**错误响应**（502）：
```json
{
  "detail": "删除 Flow 失败: ..."
}
```

---

## 9. Prompt 管理

### 9.1 创建 Prompt

**请求方式**：`POST`

**请求地址**：`/prompts/add`

**请求参数**：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| prompt_name | string | 是 | - | Prompt 名称 |
| content | string | 是 | - | Prompt 内容 |
| prompt_type | string | 否 | `common` | Prompt 类型 |
| scene | string | 否 | null | 场景 |
| sub_scene | string | 否 | null | 子场景 |
| user_name | string | 否 | null | 用户名 |
| sys_code | string | 否 | null | 系统编码 |

**请求示例**：
```bash
curl -X POST http://localhost:8080/prompts/add \
  -H "Content-Type: application/json" \
  -d '{
    "prompt_name": "nl2sql_prompt",
    "content": "你是一个 SQL 生成专家...",
    "prompt_type": "common",
    "scene": "chat_data"
  }'
```

**正常响应**（200）：
```json
{
  "ok": true,
  "prompt": {
    "prompt_name": "nl2sql_prompt",
    "content": "你是一个 SQL 生成专家...",
    "prompt_type": "common"
  }
}
```

**错误响应**（502）：
```json
{
  "detail": "创建 Prompt 失败: ..."
}
```

---

### 9.2 更新 Prompt

**请求方式**：`POST`

**请求地址**：`/prompts/update`

**请求参数**：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| prompt_name | string | 是 | - | Prompt 名称 |
| content | string | 否 | null | Prompt 内容 |
| prompt_type | string | 否 | null | Prompt 类型 |
| scene | string | 否 | null | 场景 |
| sub_scene | string | 否 | null | 子场景 |
| user_name | string | 否 | null | 用户名 |
| sys_code | string | 否 | null | 系统编码 |

**请求示例**：
```bash
curl -X POST http://localhost:8080/prompts/update \
  -H "Content-Type: application/json" \
  -d '{
    "prompt_name": "nl2sql_prompt",
    "content": "更新后的 Prompt 内容..."
  }'
```

**正常响应**（200）：
```json
{
  "ok": true,
  "prompt": {
    "prompt_name": "nl2sql_prompt",
    "content": "更新后的 Prompt 内容..."
  }
}
```

**错误响应**（502）：
```json
{
  "detail": "更新 Prompt 失败: ..."
}
```

---

### 9.3 删除 Prompt

**请求方式**：`POST`

**请求地址**：`/prompts/delete`

**Query 参数**：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| prompt_name | string | 否 | `""` | Prompt 名称 |
| user_name | string | 否 | `""` | 用户名 |
| sys_code | string | 否 | `""` | 系统编码 |

**请求示例**：
```bash
curl -X POST "http://localhost:8080/prompts/delete?prompt_name=nl2sql_prompt"
```

**正常响应**（200）：
```json
{
  "ok": true,
  "deleted": true
}
```

**错误响应**（502）：
```json
{
  "detail": "删除 Prompt 失败: ..."
}
```

---

### 9.4 列出 Prompt

**请求方式**：`POST`

**请求地址**：`/prompts/list`

**请求参数**：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| user_name | string | 否 | null | 用户名 |
| sys_code | string | 否 | null | 系统编码 |
| page | int | 否 | 1 | 页码 |
| page_size | int | 否 | 20 | 每页条数 |

**请求示例**：
```bash
curl -X POST http://localhost:8080/prompts/list \
  -H "Content-Type: application/json" \
  -d '{"page":1,"page_size":10}'
```

**正常响应**（200）：
```json
{
  "ok": true,
  "prompts": [
    {
      "prompt_name": "nl2sql_prompt",
      "content": "你是一个 SQL 生成专家...",
      "prompt_type": "common"
    }
  ]
}
```

**错误响应**（502）：
```json
{
  "detail": "获取 Prompt 列表失败: ..."
}
```

---

### 9.5 获取 Prompt 类型目标

**请求方式**：`GET`

**请求地址**：`/prompts/type/targets`

**请求参数**：无

**请求示例**：
```bash
curl http://localhost:8080/prompts/type/targets
```

**正常响应**（200）：
```json
{
  "ok": true,
  "targets": [
    {"key": "common", "name": "通用"},
    {"key": "scene", "name": "场景"}
  ]
}
```

**错误响应**（502）：
```json
{
  "detail": "获取 Prompt 类型目标失败: ..."
}
```

---

## 10. App 管理

### 10.1 列出所有 App

**请求方式**：`GET`

**请求地址**：`/apps` 或 `/apps/`

**请求参数**：无

**请求示例**：
```bash
curl http://localhost:8080/apps
```

**正常响应**（200）：
```json
{
  "ok": true,
  "apps": [
    {
      "app_code": "app_001",
      "app_name": "数据分析助手",
      "app_describe": "帮助用户进行数据分析",
      "team_mode": "single_agent",
      "language": "zh",
      "icon": "📊"
    }
  ]
}
```

**错误响应**（502）：
```json
{
  "detail": "获取 App 列表失败: ..."
}
```

---

### 10.2 获取 App 详情

**请求方式**：`GET`

**请求地址**：`/apps/{app_id}`

**路径参数**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| app_id | string | 是 | App ID（app_code） |

**请求示例**：
```bash
curl http://localhost:8080/apps/app_001
```

**正常响应**（200）：
```json
{
  "ok": true,
  "app": {
    "app_code": "app_001",
    "app_name": "数据分析助手",
    "app_describe": "帮助用户进行数据分析",
    "team_mode": "single_agent",
    "language": "zh",
    "icon": "📊"
  }
}
```

**错误响应**（502）：
```json
{
  "detail": "获取 App 失败: ..."
}
```

---

## 11. 外部平台兼容接口

> **设计说明**：以下接口的**请求地址**与外部平台（http://10.12.60.26:30541/knowledge Swagger 文档）完全一致，请求/响应格式也保持统一，数据来源为本地 DB-GPT 实例。路由模块为 `modules/external.py`（无 prefix 路由），前端平台可按统一格式无缝调用。

### 11.1 获取模型配置列表

**请求方式**：`POST`

**请求地址**：`/openPlatform/api/v1/model/config/page`

**参照外部平台**：`POST /openPlatform/api/v1/model/config/page`（地址完全一致）

**请求参数**：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| currentPage | int | 否 | 1 | 当前页码 |
| pageSize | int | 否 | 1000 | 每页条数 |

**请求示例**：
```bash
curl -X POST http://localhost:8080/openPlatform/api/v1/model/config/page \
  -H "Content-Type: application/json" \
  -d '{"currentPage":1,"pageSize":1000}'
```

**正常响应**（200）：
```json
{
  "code": 200,
  "msg": "Success",
  "success": true,
  "data": [
    {
      "id": 1,
      "sourceName": "TS",
      "modelName": "TS/GLM-5.2",
      "categoryId": 0,
      "categoryName": null,
      "baseModelType": 0,
      "enableThinking": false,
      "status": 1,
      "remark": null,
      "isDeleted": 0,
      "createTime": null,
      "updateTime": null,
      "availableEndpointNum": null,
      "totalEndpointNum": null
    }
  ],
  "pageInfo": {
    "currentPage": 1,
    "pageSize": 1000,
    "total": 2
  },
  "count": 0
}
```

**错误响应**（502）：
```json
{
  "detail": "获取模型配置失败: ..."
}
```

---

### 11.2 获取数据源配置列表

**请求方式**：`POST`

**请求地址**：`/knowledge/llm/userDataSource/get/page/v1`

**参照外部平台**：`POST /knowledge/llm/userDataSource/get/page/v1`（地址完全一致）

**请求参数**：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| currentPage | int | 否 | 1 | 当前页码 |
| pageSize | int | 否 | 1000 | 每页条数 |
| dbName | string | 否 | `""` | 数据库名（过滤） |

**请求示例**：
```bash
curl -X POST http://localhost:8080/knowledge/llm/userDataSource/get/page/v1 \
  -H "Content-Type: application/json" \
  -d '{"currentPage":1,"pageSize":1000,"dbName":""}'
```

**正常响应**（200）：
```json
{
  "code": 200,
  "msg": "Success",
  "success": true,
  "data": [
    {
      "id": 24,
      "userId": 0,
      "dbType": 0,
      "jdbcUrl": "jdbc:mysql://10.12.61.23:3299/chase_book",
      "dbName": "chase_book",
      "name": "chase_book",
      "dbSchema": "",
      "username": "root1",
      "password": "",
      "description": "CHASE 图书数据库",
      "isDeleted": 0,
      "createTime": null,
      "updateTime": null,
      "ip": "10.12.61.23",
      "port": 3299
    }
  ],
  "pageInfo": {
    "currentPage": 1,
    "pageSize": 1000,
    "total": 6
  }
}
```

**错误响应**（502）：
```json
{
  "detail": "获取数据源配置失败: ..."
}
```

---

### 11.3 创建智能体（insertAgent）

**请求方式**：`POST`

**请求地址**：`/api/v1/agent/insert`

**参照外部平台**：`POST /api/v1/agent/insert`（AgentInsertRequest，地址完全一致）

**设计说明**：接收外部平台 `AgentInsertRequest` 格式的全量参数（冗余参数原样接收后忽略），提取以下子集映射为 DB-GPT App 创建：

| AgentInsertRequest 字段 | 映射到 DB-GPT |
|-------------------------|---------------|
| `appName` | app_name（应用名称） |
| `remark` | app_describe（应用描述） |
| `modelNames[0]` | model（模型，取第一个） |
| `guideQuestions` | recommend_questions（推荐问题） |
| `settingDescription` | prompt_template（自定义提示词） |
| `varMap.dataSourceConfigs[].dbName` | database_names（数据源列表） |
| `varMap.dataSourceConfigs[].tableNames` | database_tables（预选表 {库名:[表名]}） |

**请求参数**（AgentInsertRequest）：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| appName | string | 是 | - | 智能体名称 |
| remark | string | 否 | `""` | 描述 |
| modelNames | array | 否 | `[]` | 关联的模型名称列表（取第一个使用） |
| guideQuestions | array | 否 | `[]` | 引导/推荐问题列表 |
| openingMessage | string | 否 | `""` | 开场白（映射到 app_describe 的备选） |
| settingDescription | string | 否 | `""` | 设定描述/提示词 |
| appCategoryId | int | 否 | 0 | 业务分类ID（冗余） |
| appExtraInfo | string | 否 | `""` | 额外信息（冗余） |
| enableSuggestedQuestions | int | 否 | 0 | 开启推荐问题（冗余） |
| errorMessage | string | 否 | `""` | 错误提示（冗余） |
| frontendPageUrl | string | 否 | `""` | 前端页面URL（冗余） |
| icon | string | 否 | `""` | 图标（冗余） |
| interval | int | 否 | 0 | 单位时间数量（冗余） |
| isDefault | int | 否 | 0 | 是否默认（冗余） |
| limited | int | 否 | 0 | 是否限流（冗余） |
| managementMode | int | 否 | 0 | 管理方式（冗余） |
| permits | int | 否 | 0 | 允许次数（冗余） |
| sessionType | int | 否 | 0 | 会话类型（冗余） |
| source | int | 否 | 0 | 来源（冗余） |
| strategyName | string | 否 | `""` | 策略名称（冗余） |
| strategyRemark | string | 否 | `""` | 策略备注（冗余） |
| tokens | int | 否 | 0 | tokens余量（冗余） |
| type | int | 否 | 1 | 智能体大类（冗余） |
| unit | string | 否 | `""` | 时间单位（冗余） |
| userIds | array | 否 | `[]` | 关联用户id（冗余） |
| varMap | object | 否 | `{}` | 全局变量（含 dataSourceConfigs） |
| visible | int | 否 | 1 | 是否可见（冗余） |
| workflowId | string | 否 | `""` | 工作流ID（冗余） |
| workflowSite | string | 否 | `""` | 工作流站点（冗余） |

**varMap.dataSourceConfigs 子结构**：

| 字段 | 类型 | 说明 |
|------|------|------|
| dbName | string | 数据库名 |
| tableNames | array | 预选表名列表 |

**请求示例**：
```bash
curl -X POST http://localhost:8080/api/v1/agent/insert \
  -H "Content-Type: application/json" \
  -d '{
    "appName": "双11电商分析助手",
    "remark": "基于chase_double11的电商数据分析",
    "modelNames": ["TS/GLM-5.2"],
    "guideQuestions": ["双十一有哪些商家参与活动", "哪个平台影响力最大"],
    "settingDescription": "",
    "appCategoryId": 0,
    "managementMode": 0,
    "source": 0,
    "type": 1,
    "visible": 1,
    "enableSuggestedQuestions": 0,
    "isDefault": 0,
    "limited": 0,
    "permits": 0,
    "interval": 0,
    "unit": "",
    "tokens": 0,
    "sessionType": 0,
    "varMap": {
      "dataSourceConfigs": [
        {"dbName": "chase_double11", "tableNames": ["活动", "商品"]}
      ]
    }
  }'
```

**正常响应**（200）：
```json
{
  "code": 200,
  "msg": "Success",
  "success": true,
  "data": {
    "appCode": "af524ae0-b1a6-11f1-a35d-0242ac160002",
    "appName": "双11电商分析助手"
  }
}
```

**错误响应**（400 / 502）：
```json
{
  "detail": "应用名已存在，请换一个名称"
}
```

---

### 11.4 获取应用配置详情（agent/detail）

**请求方式**：`POST`

**请求地址**：`/knowledge/api/v1/agent/detail`

**参照外部平台**：`POST /knowledge/api/v1/agent/detail`（AgentDetailRequest）

**功能说明**：根据 app_code 返回应用完整配置信息（AgentDetailVO 格式），含数据源绑定、模型配置、开场白、引导问题等。

**请求参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | string | 是 | app_code（UUID） |

**请求示例**：
```bash
curl -X POST http://localhost:8080/knowledge/api/v1/agent/detail \
  -H "Content-Type: application/json" \
  -d '{"id": "59359968-b1bb-11f1-a35d-0242ac160002"}'
```

**正常响应示例**：
```json
{
    "code": 200,
    "msg": "Success",
    "success": true,
    "data": {
        "id": "59359968-...",
        "appId": "59359968-...",
        "appName": "测试应用",
        "remark": "描述",
        "openingMessage": "你好",
        "guideQuestions": ["问题1", "问题2"],
        "type": 2,
        "limited": 0,
        "managementMode": 3,
        "sessionType": 10,
        "source": 0,
        "visible": 1,
        "enableSuggestedQuestions": 1,
        "varMap": {
            "modelConfig": {
                "modelType": "TS/GLM-5.2",
                "temperature": 0.7,
                "maxTokens": 4000,
                "topP": 1.0,
                "frequencyPenalty": 0.0,
                "presencePenalty": 0.0,
                "enableThinking": false,
                "historyRounds": 3,
                "baseModel": "openai"
            },
            "dataSourceConfigs": [
                {"databaseId": 24, "dbName": "chase_book", "tableNames": ["图书"]}
            ],
            "knowledgeGraphConfigs": []
        }
    }
}
```

---

### 11.5 批量查数据源（dbNamesByIds）

**请求方式**：`POST`

**请求地址**：`/knowledge/llm/userDataSource/get/dbNamesByIds/v1`

**参照外部平台**：`POST /knowledge/llm/userDataSource/get/dbNamesByIds/v1`

**功能说明**：根据数据源 ID 列表返回数据源简要信息。

**请求参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| ids | array\<int\> | 是 | 数据源 ID 列表 |

**请求示例**：
```bash
curl -X POST http://localhost:8080/knowledge/llm/userDataSource/get/dbNamesByIds/v1 \
  -H "Content-Type: application/json" \
  -d '{"ids": [24]}'
```

**正常响应示例**：
```json
{
    "code": 200,
    "msg": "Success",
    "success": true,
    "data": [
        {"id": 24, "dbName": "chase_book", "name": "chase_book", "ip": "db-gpt-db-1", "port": 3306}
    ]
}
```

---

### 11.6 获取数据表列表（getTablesFromDataSource）

**请求方式**：`POST`

**请求地址**：`/knowledge/llm/userDataSource/getTablesFromDataSource/v1`

**参照外部平台**：`POST /knowledge/llm/userDataSource/getTablesFromDataSource/v1`

**功能说明**：获取指定数据源的所有表名 + 表注释。

**请求参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | int | 是 | 数据源 ID |
| tableNames | array\<string\> | 否 | 表名过滤（空=全部） |

**请求示例**：
```bash
curl -X POST http://localhost:8080/knowledge/llm/userDataSource/getTablesFromDataSource/v1 \
  -H "Content-Type: application/json" \
  -d '{"id": 24, "tableNames": []}'
```

**正常响应示例**：
```json
{
    "code": 200,
    "msg": "Success",
    "success": true,
    "data": [
        {"tableName": "图书", "comment": ""},
        {"tableName": "平台", "comment": ""}
    ]
}
```

---

### 11.7 获取表列信息（table/getComments）

**请求方式**：`POST`

**请求地址**：`/knowledge/llm/userDataSource/table/getComments/v1`

**参照外部平台**：`POST /knowledge/llm/userDataSource/table/getComments/v1`

**功能说明**：获取指定数据源中指定表的列信息。

**请求参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | int | 是 | 数据源 ID |
| tableName | string | 是 | 表名 |

**请求示例**：
```bash
curl -X POST http://localhost:8080/knowledge/llm/userDataSource/table/getComments/v1 \
  -H "Content-Type: application/json" \
  -d '{"id": 24, "tableName": "图书"}'
```

**正常响应示例**：
```json
{
    "code": 200,
    "msg": "Success",
    "success": true,
    "data": [
        {
            "columnName": "图书id",
            "dataType": "VARCHAR(255)",
            "maxLength": null,
            "isNullable": "NO",
            "defaultValue": null,
            "comment": "图书ID",
            "columnChName": null,
            "enumMap": null,
            "reverseEnumMap": {}
        }
    ]
}
```

---

### 11.8 修改表+列注释（table/updateTableComments）

**请求方式**：`POST`

**请求地址**：`/knowledge/llm/userDataSource/table/updateTableComments/v1`

**参照外部平台**：`POST /knowledge/llm/userDataSource/table/updateTableComments/v1`

**功能说明**：修改表注释 + 列注释（ALTER TABLE ... COMMENT + MODIFY COLUMN ... COMMENT）。

**请求参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | int | 是 | 数据源 ID |
| tableName | string | 是 | 表名 |
| tableComment | string | 否 | 表注释 |
| tableColumnInfos | array\<object\> | 否 | 列信息列表，每项含 columnName/comment/dataType |

**请求示例**：
```bash
curl -X POST http://localhost:8080/knowledge/llm/userDataSource/table/updateTableComments/v1 \
  -H "Content-Type: application/json" \
  -d '{"id": 24, "tableName": "图书", "tableComment": "图书表", "tableColumnInfos": [{"columnName": "图书id", "comment": "图书ID", "dataType": "varchar"}]}'
```

**正常响应示例**：
```json
{
    "code": 200,
    "msg": "Success",
    "success": true,
    "data": "更新成功"
}
```

---

### 11.9 编辑保存智能体（agent/update）

**请求方式**：`POST`

**请求地址**：`/knowledge/api/v1/agent/update`

**参照外部平台**：`POST /knowledge/api/v1/agent/update`（AgentUpdateRequest）

**功能说明**：编辑保存智能体配置，含开场白、引导问题、模型配置、数据源+选表。

**请求参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | string | 是 | app_code |
| appName | string | 否 | 应用名称 |
| remark | string | 否 | 描述 |
| openingMessage | string | 否 | 开场白 |
| guideQuestions | array\<string\> | 否 | 引导问题列表 |
| settingDescription | string | 否 | 设定描述/提示词 |
| varMap | object | 否 | 含 modelConfig + dataSourceConfigs |
| varMap.modelConfig | object | 否 | 模型配置（modelType/temperature/maxTokens/topP/...） |
| varMap.dataSourceConfigs | array | 否 | 数据源配置（databaseId/dbName/tableNames） |
| type | int | 否 | 智能体大类（冗余，默认2） |
| limited | int | 否 | 是否限流（冗余，默认0） |
| managementMode | int | 否 | 管理方式（冗余，默认3） |

**请求示例**：
```bash
curl -X POST http://localhost:8080/knowledge/api/v1/agent/update \
  -H "Content-Type: application/json" \
  -d '{
    "id": "59359968-...",
    "appName": "测试应用",
    "remark": "描述",
    "openingMessage": "你好",
    "guideQuestions": ["问题1"],
    "varMap": {
      "modelConfig": {"modelType": "TS/GLM-5.2", "temperature": 0.7, "maxTokens": 4000, "topP": 1.0},
      "dataSourceConfigs": [{"databaseId": 24, "dbName": "chase_book", "tableNames": ["图书"]}]
    },
    "type": 2, "limited": 0, "managementMode": 3
  }'
```

**正常响应示例**：
```json
{
    "code": 200,
    "msg": "Success",
    "success": true,
    "data": true
}
```

**处理流程**：
1. 调 DB-GPT `/app/edit` 更新应用（resources + model + temperature + max_new_tokens）
2. 修复 `published` 为 `true`（DB-GPT edit 后默认 false，会导致 detail 查询失败）
3. 写辅助表 `app_extra_config`（opening_message / guide_questions / model_config_extra / temperature / max_new_tokens）
4. 同步写 `recommend_question` 表（user_code 与 gpts_app 一致，params 设为 `{}` 避免 DB-GPT detail 查询 JSON 解析错误）

**前端联动**（2026-09-16）：

| 前端函数 | 调用接口 | 说明 |
|----------|----------|------|
| `editAppConfig(appCode)` | `POST /knowledge/api/v1/agent/detail` | 编辑弹窗加载：获取应用完整配置（含 modelConfig / dataSourceConfigs / guideQuestions / openingMessage） |
| `submitEditAppConfig(appCode)` | `POST /knowledge/api/v1/agent/update` | 编辑保存：提交 AgentUpdateRequest 格式，含模型配置 + 数据源选表 + 开场白 + 引导问题 |
| `expandTablePickers(mode)` | — | 先勾选数据库，再点"编辑已选数据表"按钮统一加载表列表（不自动展开） |
| `onAppDsCheck(checkbox, mode)` | — | 勾选/取消勾选数据源时仅更新摘要，不再自动展开表选择器 |
| `showCreateAppModal()` | `POST /openPlatform/api/v1/model/config/page` + `POST /knowledge/llm/userDataSource/get/page/v1` | 创建弹窗加载模型和数据源列表（外部平台格式） |
| `createApp()` | `POST /api/v1/agent/insert` | 创建智能体（AgentInsertRequest 格式） |

---

## 12. 评估管理

### 11.1 运行评估

**请求方式**：`POST`

**请求地址**：`/evaluation/run`

**请求参数**：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| evaluate_code | string | 否 | null | 评估代码 |
| scene_key | string | 否 | null | 场景 key |
| scene_value | string | 否 | null | 场景值 |
| datasets_name | string | 否 | null | 数据集名称 |
| datasets | array | 否 | null | 数据集 |
| evaluate_metrics | array | 否 | null | 评估指标 |
| context | object | 否 | null | 上下文 |
| user_name | string | 否 | null | 用户名 |
| user_id | string | 否 | null | 用户 ID |
| sys_code | string | 否 | null | 系统编码 |
| parallel_num | int | 否 | null | 并发数 |

**请求示例**：
```bash
curl -X POST http://localhost:8080/evaluation/run \
  -H "Content-Type: application/json" \
  -d '{
    "evaluate_code": "eval_001",
    "scene_key": "chat_data",
    "scene_value": "nl2sql",
    "datasets_name": "chase_test",
    "parallel_num": 4
  }'
```

**正常响应**（200）：
```json
{
  "ok": true,
  "results": [
    {
      "question": "列出所有书名",
      "answer": "...",
      "score": 0.95,
      "metric": "accuracy"
    }
  ]
}
```

**错误响应**（502）：
```json
{
  "detail": "运行评估失败: ..."
}
```

---

## 附录：根路径与健康检查

### 根路径

**请求方式**：`GET`

**请求地址**：`/`

**正常响应**（200）：
```json
{
  "service": "智能问数 Agent",
  "version": "1.0.0",
  "dbgpt_api_base": "http://db-gpt-webserver-1:5670/api/v2",
  "model": "TS-MOMA/DeepSeek-V4-Flash",
  "docs": "/docs"
}
```

### 健康检查

**请求方式**：`GET`

**请求地址**：`/health`

**正常响应**（200）：
```json
{
  "status": "ok",
  "model": "TS-MOMA/DeepSeek-V4-Flash",
  "dbgpt": "http://db-gpt-webserver-1:5670/api/v2"
}
```

---

## 附录：ChatMode 枚举值

| 枚举名 | 值 | 说明 |
|--------|------|------|
| NORMAL | `chat_normal` | 普通对话 |
| DATA | `chat_data` | 数据对话（NL2SQL） |
| KNOWLEDGE | `chat_knowledge` | 知识库问答 |
| FLOW | `chat_flow` | AWEL Flow 问答 |
| APP | `chat_app` | App 问答 |
| DB_QA | `chat_with_db_qa` | DB 问答（旧模式） |
| DASHBOARD | `chat_dashboard` | 仪表盘 |

---

## 13. 外部平台兼容 — 带有多个数据源聊天

### 13.1 数据库对话（流式 SSE）

**请求方式**：`POST`

**请求地址**：`/knowledge/llm/ai-analyze/chatWithDb/v1`

**接口说明**：应用管理界面的调试预览接口。前端只需传 `instanceId`（应用 app_code）+ `question` + `model`，后端自动从应用配置解析绑定的数据源/知识库/提示词。`session` 为空时表示"重新开始"（新建会话，不带上下文）。

**请求参数**：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| question | string | 是 | - | 用户问题 |
| instanceId | string | 是 | - | 应用 ID（app_code） |
| model | string | 否 | `""` | 临时选中的模型（空=用应用配置的模型） |
| isGraph | bool | 否 | false | 是否启用知识图谱（暂不支持，接收忽略） |
| queryMode | int | 否 | 0 | 查询模式（0=自动，接收忽略） |
| tableNames | string[] | 否 | `[]` | 临时预选表（覆盖应用配置的预选表） |
| session | string | 否 | `""` | 会话 ID（空=新建会话=重新开始） |
| prompt | string | 否 | `""` | 临时提示词文本（覆盖应用配置的提示词，通过 prompt_code 注入到 system prompt 指定位置） |

**响应**：SSE 流式响应（`text/event-stream`），格式与 `/ask/react-agent` 完全一致。

**SSE 事件类型**：

| type | 说明 |
|------|------|
| opening | 开场白（应用配置的 openingMessage） |
| context.status | 上下文预算 |
| step.start | 推理步骤开始 |
| step.meta | 步骤元信息（thought / action / action_input） |
| step.chunk | 步骤输出内容 |
| step.done | 步骤完成 |
| final | 最终回答 |
| done | 流结束 |
| error | 错误 |

**后端处理逻辑**：

1. 用 `instanceId` 调 DB-GPT `GET /app/{app_code}` 获取应用详情
2. 从 `details[].resources` 解析绑定的数据源名列表 + 预选表 + 知识库 + 模型名 + 提示词
3. 查 `app_extra_config` 获取 temperature/max_new_tokens/opening_message
4. `model` 覆盖：请求体 `model` 非空则覆盖应用模型
5. `tableNames` 覆盖：请求体 `tableNames` 非空则覆盖第一个数据源的预选表
6. `prompt` 覆盖：请求体 `prompt` 非空则作为 `prompt_code` 传入（覆盖应用配置的提示词）
7. `session` 处理：空=新建 UUID 会话（重新开始），非空=复用已有会话
8. 调 `QnAAgent.ask_react_stream()` 流式输出

**请求示例**：

```json
{
  "question": "数据库里有哪些表",
  "instanceId": "4cab71ee-b1c6-11f1-bfd7-0242ac160002",
  "model": "",
  "isGraph": false,
  "queryMode": 0,
  "tableNames": [],
  "session": "",
  "prompt": ""
}
```

**响应示例**（SSE 流）：

```
data: {"type": "opening", "content": "你好，我是数据分析助手"}
data: {"type": "context.status", "used": 8901, "budget": 115904, "ratio": 0.0768, "state": "normal", "compact_layer": null}
data: {"type": "step.start", "step": 1, "id": "step-1", "title": "思考中", "detail": "Thought/Action/Observation"}
data: {"type": "step.meta", "step": 1, "thought": "...", "action": "sql_query", ...}
data: {"type": "final", "content": "数据库中有以下表：..."}
data: [DONE]
```

**前端对接**：
- 应用管理页卡片新增"调试"按钮 → 打开全屏调试预览页面
- 调试预览页面布局：顶部模型选择+重新开始按钮，中间数据源选择区+消息区（复用 React Agent SSE 渲染），底部输入框
- 数据源选择区：复用第一部分编辑弹窗的"选择数据源"弹窗（showSelectDsModal）和"数据源编辑"全屏页面（showDsEditPage），通过 `_dsMode` 标志区分当前操作上下文
- 进入调试时自动回显应用已绑定的数据源（从 agent/detail 的 dataSourceConfigs 加载到 `_debugBoundDs`）
- `dataSourceConfigs` 字段：非空时覆盖应用绑定的数据源，空则使用应用配置
- 提示词输入框：可覆盖应用配置的提示词（`prompt` 字段）
- "重新开始"按钮：清空 `session` 字段 → 后端新建会话（不带上下文 ID）
- SSE 渲染逻辑：复用 `sendReactAgent` 的 step.start/step.meta/step.chunk/step.final 渲染，适配调试预览的 DOM 容器
- `session` 字段：首次请求为空（新建），后续从 SSE `type: "session"` 事件中捕获 `conv_uid` 并复用

---

## 附录：接口统计

| 模块 | 接口数 | 路由前缀 | 备注 |
|------|--------|----------|------|
| 问答 | 7+2废弃 | `/ask` | 统一接口 + 会话管理 + 旧接口兼容 |
| 数据源 | 8 | `/datasources` | |
| 知识库 | 11 | `/knowledge` | |
| MCP 连接器 | 10 | `/connectors` | |
| 会话 | 6 | `/conversations` | |
| 模型 | 4 | `/models` | |
| AWEL Flow | 5 | `/flows` | |
| Prompt | 5 | `/prompts` | |
| App | 2 | `/apps` | |
| 外部平台兼容 | 10 | 无 prefix（与外部平台路径一致） | 模型配置/数据源配置/insert/detail/update/dbNamesByIds/getTables/getComments/updateComments/chatWithDb |
| 评估 | 1 | `/evaluation` | |
| 系统 | 2 | `/` `/health` | |
| **合计** | **73** | - | 含 2 个 deprecated 旧接口 |
