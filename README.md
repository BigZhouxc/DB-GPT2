# 智能问数 Agent

基于 **DB-GPT SDK (dbgpt_client)** 封装的统一智能问数服务。

## 架构

```
客户端 (curl/Postman/前端)
  ↓ HTTP
qna_agent (FastAPI, :8080)
  ├── core/       — 客户端工厂 + 会话管理 + 核心问答
  └── modules/    — 10 个功能模块
  ↓ HTTP (dbgpt_client)
DB-GPT Server (:5670)   ← 必须运行
  ↓
LLM (DeepSeek) + MySQL (CHASE 数据)
```

## 前置条件

1. **DB-GPT Server 运行中**（默认 `http://127.0.0.1:5670`）
2. Python 3.10+

## 安装

```bash
pip install -r requirements.txt
```

## 启动

```bash
# 设置环境变量（可选，默认值如下）
export DBGPT_API_BASE=http://127.0.0.1:5670/api/v2
export MODEL=TS-MOMA/DeepSeek-V4-Flash

# 启动服务
conda run -n doubao_env python -m uvicorn app:app --host 0.0.0.0 --port 8080

# 访问 Swagger 文档
# http://localhost:8080/docs
```

## 端到端验证结果

所有接口已通过 DB-GPT 0.8.2 实际环境验证：

| 模块 | 接口 | 状态 |
|---|---|---|
| 数据源 | 列表/详情/类型/测试连接/刷新/CRUD | ✓ 12 个数据源, 18 种 DB 类型 |
| 知识库 | 空间列表/详情/文档列表/检索 | ✓ 1 个空间, 4 个文档 |
| 问答 | NL2SQL ask/stream/knowledge/flow | ✓ SQL 生成+执行+数据返回 |
| 会话 | 列表/新建/删除/清空/历史/分页 | ✓ 返回历史会话 |
| 模型 | 类型/列表/启停 | ✓ 351 种类型, 2 个运行中 |
| MCP | 类型/CRUD/测试/工具/确认 | ✓ 连接器类型列表 |
| Flow | CRUD | ✓ |
| Prompt | CRUD/类型目标 | ✓ |
| App | 列表/详情 | ✓ |

```bash
# 方式 1：直接启动
uvicorn app:app --host 0.0.0.0 --port 8080

# 方式 2：带环境变量
DBGPT_API_BASE=http://127.0.0.1:5670/api/v2 \
MODEL=TS-MOMA/DeepSeek-V4-Flash \
uvicorn app:app --host 0.0.0.0 --port 8080
```

启动后访问 `http://localhost:8080/docs` 查看 Swagger 文档。

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DBGPT_API_BASE` | `http://127.0.0.1:5670/api/v2` | DB-GPT API 地址 |
| `DBGPT_API_KEY` | (空) | DB-GPT API Key |
| `MODEL` | `TS-MOMA/DeepSeek-V4-Flash` | 默认模型名 |
| `TIMEOUT` | `300` | 请求超时秒数 |

## 接口清单

### 问答（核心）

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/ask/` | 数据对话（NL2SQL） |
| `POST` | `/ask/stream` | 流式问答（SSE） |
| `POST` | `/ask/knowledge` | 知识库问答 |
| `POST` | `/ask/flow` | AWEL Flow 问答 |
| `GET` | `/ask/chat-modes` | 支持的问答模式 |
| `POST` | `/ask/session/new` | 新建会话 |
| `GET` | `/ask/sessions` | 列出所有会话 |
| `DELETE` | `/ask/sessions/{key}` | 移除会话 |
| `POST` | `/ask/sessions/reset` | 清空会话 |

### 数据源管理

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/datasources` | 列出所有数据源 |
| `GET` | `/datasources/{id}` | 获取数据源详情 |
| `POST` | `/datasources` | 新建数据源 |
| `PUT` | `/datasources` | 更新数据源 |
| `DELETE` | `/datasources/{id}` | 删除数据源 |
| `GET` | `/datasources/types/list` | 支持的数据源类型 |
| `POST` | `/datasources/test-connection` | 测试连接 |
| `POST` | `/datasources/{id}/refresh` | 刷新元信息 |

### 知识库管理

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/knowledge/spaces` | 列出知识空间 |
| `GET` | `/knowledge/spaces/{id}` | 空间详情 |
| `POST` | `/knowledge/spaces` | 创建空间 |
| `PUT` | `/knowledge/spaces` | 更新空间 |
| `DELETE` | `/knowledge/spaces/{id}` | 删除空间 |
| `GET` | `/knowledge/documents` | 列出文档 |
| `GET` | `/knowledge/documents/{id}` | 文档详情 |
| `POST` | `/knowledge/documents` | 创建文档 |
| `DELETE` | `/knowledge/documents/{id}` | 删除文档 |
| `POST` | `/knowledge/documents/sync` | 同步文档 |
| `POST` | `/knowledge/spaces/{id}/retrieve` | 知识库检索 |

### MCP 连接器

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/connectors/types` | 连接器类型 |
| `GET` | `/connectors` | 列出连接器 |
| `GET` | `/connectors/{id}` | 连接器详情 |
| `POST` | `/connectors` | 创建连接器 |
| `PUT` | `/connectors/{id}` | 更新连接器 |
| `DELETE` | `/connectors/{id}` | 删除连接器 |
| `POST` | `/connectors/{id}/test` | 测试连接 |
| `GET` | `/connectors/{id}/tools` | 工具列表 |
| `GET` | `/connectors/pending-confirms` | 待确认列表 |
| `POST` | `/connectors/confirm` | 确认操作 |

### 会话管理

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/conversations/new` | 新建会话 |
| `GET` | `/conversations/list` | 列出会话 |
| `POST` | `/conversations/delete` | 删除会话 |
| `POST` | `/conversations/clear` | 清空会话 |
| `GET` | `/conversations/messages/history` | 历史消息 |
| `POST` | `/conversations/query_page` | 分页查询 |

### 模型管理

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/models/model-types` | 模型类型 |
| `GET` | `/models/list` | 模型列表 |
| `POST` | `/models/start` | 启动模型 |
| `POST` | `/models/stop` | 停止模型 |

### AWEL Flow

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/flows` | 列出 Flow |
| `GET` | `/flows/{id}` | Flow 详情 |
| `POST` | `/flows` | 创建 Flow |
| `PUT` | `/flows/{uid}` | 更新 Flow |
| `DELETE` | `/flows/{id}` | 删除 Flow |

### Prompt 管理

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/prompts/add` | 创建 Prompt |
| `POST` | `/prompts/update` | 更新 Prompt |
| `POST` | `/prompts/delete` | 删除 Prompt |
| `POST` | `/prompts/list` | 列出 Prompt |
| `GET` | `/prompts/type/targets` | 类型目标 |

### App 管理

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/apps` | 列出 App |
| `GET` | `/apps/{id}` | App 详情 |

### 评估

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/evaluation/run` | 运行评估 |

## 使用示例

### 数据对话

```bash
curl -X POST http://localhost:8080/ask/ \
  -H "Content-Type: application/json" \
  -d '{"question":"列出所有书名","datasource":"chase_book"}'
```

### 流式问答

```bash
curl -N http://localhost:8080/ask/stream \
  -H "Content-Type: application/json" \
  -d '{"question":"按评分排序","datasource":"chase_book"}'
```

### 查看数据源类型

```bash
curl http://localhost:8080/datasources/types/list
```

### 测试数据库连接

```bash
curl -X POST http://localhost:8080/datasources/test-connection \
  -H "Content-Type: application/json" \
  -d '{"db_type":"mysql","db_name":"chase_book","db_host":"10.12.61.23","db_port":3299,"db_user":"root1","db_pwd":"Wlw123456!"}'
```

## 目录结构

```
qna_agent/
├── app.py                  — FastAPI 入口，挂载所有路由
├── requirements.txt        — 依赖
├── README.md              — 本文件
├── core/
│   ├── __init__.py
│   ├── client_factory.py   — DB-GPT Client 单例工厂
│   ├── session_manager.py  — 线程安全会话池
│   └── qna_agent.py        — 核心问答（NL2SQL + 解析 + 归一化）
└── modules/
    ├── __init__.py
    ├── qa.py              — 问答（核心）
    ├── datasource.py       — 数据源管理
    ├── knowledge.py        — 知识库管理
    ├── connector.py        — MCP 连接器
    ├── conversation.py     — 会话管理
    ├── model.py            — 模型管理
    ├── flow.py             — AWEL Flow
    ├── prompt.py           — Prompt 管理
    ├── app.py              — App 管理
    └── evaluation.py       — 评估
```
