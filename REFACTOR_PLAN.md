# 智能问数 Agent 服务 — 重构方案

## 一、现状分析

### 现有封装（qna_agent/）覆盖的接口

| 模块 | 已有接口 | 缺失 |
|---|---|---|
| 问答 | `/ask`（非流式）、`/ask`（流式 SSE） | — |
| 数据源 | `/datasources`（仅列表） | 类型列表、创建、更新、删除、测试连接、刷新 |
| 会话 | `/session/new`（仅新建） | 历史消息、列表、删除、清空 |
| 知识库 | 无 | 全部 |
| MCP 连接器 | 无 | 全部 |
| 模型管理 | 无 | 全部 |
| AWEL Flow | 无 | 全部 |
| Prompt | 无 | 全部 |
| App | 无 | 全部 |
| 评估 | 无 | 全部 |

### DB-GPT SDK 能力盘点

`dbgpt_client` 包提供两类能力：

**A. 封装好的函数（直接调用）**
- `datasource.py`: `create_datasource` / `update_datasource` / `delete_datasource` / `get_datasource` / `list_datasource`
- `knowledge.py`: `create_space` / `update_space` / `delete_space` / `get_space` / `list_space` / `create_document` / `delete_document` / `get_document` / `list_document` / `sync_document`
- `app.py`: `get_app` / `list_app`
- `flow.py`: `create_flow` / `update_flow` / `delete_flow` / `get_flow` / `list_flow` / `run_flow_cmd`
- `evaluation.py`: `run_evaluation`
- `client.py`: `chat` / `chat_stream`（已有）

**B. 通用 HTTP 方法（需自行封装 serve 路径）**

`Client` 暴露了 `get/post/put/delete/patch` 方法，自动拼接 `/api/v2/serve` 前缀。以下 Serve API 无 SDK 函数但可通过通用方法调用：

| Serve 模块 | 路由前缀 | 功能 |
|---|---|---|
| datasource-types | `/datasources/datasource-types` | 查看支持的数据库类型 |
| test-connection | `/datasources/test-connection` | 测试数据库连接 |
| refresh | `/datasources/{id}/refresh` | 刷新数据源 |
| connector (MCP) | `/connectors/*` | 连接器类型/CRUD/测试/工具列表 |
| conversation | `/conversations/*` | 会话 CRUD/历史消息/导出 |
| model | `/models/*` | 模型类型/列表/启动/停止 |
| prompt | `/prompts/*` | Prompt CRUD |
| rag retrieve | `/spaces/{id}/retrieve` | 知识库检索 |

## 二、目标架构

### 目录结构

```
qna_agent/
├── core/
│   ├── __init__.py
│   ├── client.py              # DB-GPT Client 工厂（单例化管理）
│   ├── chat.py                # 问答核心：QnAAgent（保留现有 ask/ask_stream + 增强）
│   └── response.py            # 统一响应格式
├── modules/
│   ├── __init__.py
│   ├── datasource.py          # 数据源管理（类型/CRUD/测试连接/刷新）
│   ├── knowledge.py           # 知识库管理（空间/文档/同步/检索）
│   ├── conversation.py        # 会话管理（新建/列表/历史/删除/清空）
│   ├── connector.py           # MCP 连接器管理（类型/CRUD/测试/工具）
│   ├── model.py               # 模型管理（类型/列表/启停）
│   ├── flow.py                # AWEL Flow 管理（CRUD/执行）
│   ├── prompt.py              # Prompt 管理（CRUD）
│   ├── app.py                 # App 管理（列表/详情）
│   └── evaluation.py          # 评估管理（运行评估）
├── app.py                     # FastAPI 服务入口（统一路由注册）
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── README.md
```

### 设计原则

1. **分层**：core（客户端+问答核心）→ modules（按功能域拆分）→ app.py（FastAPI 路由层）
2. **每个 module 一个类**，通过统一的 `client` 单例与 DB-GPT 通信
3. **SDK 优先**：SDK 已封装的函数直接用，没有的用 `client.get/post/put/delete` 走 serve 路径
4. **统一响应**：所有接口返回 `{ "ok": bool, "data": ..., "error": "" }` 格式
5. **保留现有问答能力**：`QnAAgent` 的 `normalize_mysql_sql`、`_parse_chart_view` 等已验证的逻辑不变

## 三、完整接口清单

### 1. 数据库管理 — `/api/datasources`

| 方法 | 路径 | 说明 | SDK/通用 |
|---|---|---|---|
| GET | `/api/datasources/types` | 查看支持的数据库类型（sqlite/mysql/...） | 通用 `GET /serve/datasources/datasource-types` |
| GET | `/api/datasources` | 列出所有已注册数据源 | SDK `list_datasource` |
| GET | `/api/datasources/{id}` | 查看某个数据源详情 | SDK `get_datasource` |
| POST | `/api/datasources` | 创建/注册新数据源 | SDK `create_datasource` |
| PUT | `/api/datasources` | 更新数据源 | SDK `update_datasource` |
| DELETE | `/api/datasources/{id}` | 删除数据源 | SDK `delete_datasource` |
| POST | `/api/datasources/test-connection` | 测试连接（不创建） | 通用 `POST /serve/datasources/test-connection` |
| POST | `/api/datasources/{id}/refresh` | 刷新数据源元信息 | 通用 `POST /serve/datasources/{id}/refresh` |

### 2. 知识库管理 — `/api/knowledge`

| 方法 | 路径 | 说明 | SDK/通用 |
|---|---|---|---|
| GET | `/api/knowledge/spaces` | 列出知识空间 | SDK `list_space` |
| POST | `/api/knowledge/spaces` | 创建知识空间 | SDK `create_space` |
| GET | `/api/knowledge/spaces/{id}` | 查看空间详情 | SDK `get_space` |
| PUT | `/api/knowledge/spaces` | 更新空间 | SDK `update_space` |
| DELETE | `/api/knowledge/spaces/{id}` | 删除空间 | SDK `delete_space` |
| POST | `/api/knowledge/spaces/{id}/retrieve` | 知识检索 | 通用 `POST /serve/spaces/{id}/retrieve` |
| GET | `/api/knowledge/documents` | 列出文档 | SDK `list_document` |
| POST | `/api/knowledge/documents` | 添加文档 | SDK `create_document` |
| GET | `/api/knowledge/documents/{id}` | 查看文档 | SDK `get_document` |
| DELETE | `/api/knowledge/documents/{id}` | 删除文档 | SDK `delete_document` |
| POST | `/api/knowledge/documents/sync` | 批量同步文档 | SDK `sync_document` |
| POST | `/api/knowledge/documents/{id}/sync` | 同步单个文档 | 通用 `POST /serve/documents/{id}/sync` |

### 3. MCP 连接器管理 — `/api/connectors`

| 方法 | 路径 | 说明 | 实现方式 |
|---|---|---|---|
| GET | `/api/connectors/types` | 查看支持的连接器类型（内置 MCP + 自定义） | 通用 `GET /serve/connectors/types` |
| GET | `/api/connectors` | 列出所有连接器 | 通用 `GET /serve/connectors` |
| POST | `/api/connectors` | 创建连接器 | 通用 `POST /serve/connectors` |
| GET | `/api/connectors/{id}` | 查看连接器详情 | 通用 `GET /serve/connectors/{id}` |
| PUT | `/api/connectors/{id}` | 更新连接器 | 通用 `PUT /serve/connectors/{id}` |
| DELETE | `/api/connectors/{id}` | 删除连接器 | 通用 `DELETE /serve/connectors/{id}` |
| POST | `/api/connectors/{id}/test` | 测试连接器连通性 | 通用 `POST /serve/connectors/{id}/test` |
| GET | `/api/connectors/{id}/tools` | 获取连接器暴露的工具列表 | 通用 `GET /serve/connectors/{id}/tools` |
| GET | `/api/connectors/pending-confirms` | 待确认操作列表 | 通用 `GET /serve/connectors/pending-confirms` |
| POST | `/api/connectors/confirm` | 确认/拒绝操作 | 通用 `POST /serve/connectors/confirm` |

### 4. 会话管理 — `/api/conversations`

| 方法 | 路径 | 说明 | 实现方式 |
|---|---|---|---|
| POST | `/api/conversations/new` | 新建会话（返回 conv_uid） | 通用 `POST /serve/conversations/new` |
| GET | `/api/conversations` | 列出会话（分页） | 通用 `GET /serve/conversations/list` |
| POST | `/api/conversations/query` | 按条件查询会话 | 通用 `POST /serve/conversations/query` |
| DELETE | `/api/conversations/{conv_uid}` | 删除会话 | 通用 `POST /serve/conversations/delete` |
| POST | `/api/conversations/{conv_uid}/clear` | 清空会话历史 | 通用 `POST /serve/conversations/clear` |
| GET | `/api/conversations/{conv_uid}/messages` | 获取消息历史 | 通用 `GET /serve/conversations/messages/history` |

### 5. 模型管理 — `/api/models`

| 方法 | 路径 | 说明 | 实现方式 |
|---|---|---|---|
| GET | `/api/models/types` | 查看支持的模型类型 | 通用 `GET /serve/models/model-types` |
| GET | `/api/models` | 列出已注册/运行中的模型 | 通用 `GET /serve/models` |
| POST | `/api/models/start` | 启动模型 | 通用 `POST /serve/models/start` |
| POST | `/api/models/stop` | 停止模型 | 通用 `POST /serve/models/stop` |

### 6. 问答 — `/api/chat`（核心，保留现有 + 增强）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/chat` | 问数（非流式），返回 SQL/data/answer |
| POST | `/api/chat/stream` | 问数（SSE 流式），逐 token 返回 |
| POST | `/api/chat/knowledge` | 知识库问答（chat_mode=chat_knowledge） |
| POST | `/api/chat/flow` | AWEL Flow 问答（chat_mode=chat_flow） |
| GET | `/api/chat/modes` | 列出支持的 chat_mode |

### 7. AWEL Flow 管理 — `/api/flows`

| 方法 | 路径 | 说明 | SDK/通用 |
|---|---|---|---|
| GET | `/api/flows` | 列出 Flow（支持 name/uid 过滤） | SDK `list_flow` |
| POST | `/api/flows` | 创建 Flow | SDK `create_flow` |
| GET | `/api/flows/{uid}` | 查看 Flow | SDK `get_flow` |
| PUT | `/api/flows/{uid}` | 更新 Flow | SDK `update_flow` |
| DELETE | `/api/flows/{uid}` | 删除 Flow | SDK `delete_flow` |

### 8. Prompt 管理 — `/api/prompts`

| 方法 | 路径 | 说明 | 实现方式 |
|---|---|---|---|
| GET | `/api/prompts` | 列出 Prompt | 通用 `GET /serve/prompts/page` |
| POST | `/api/prompts` | 创建 Prompt | 通用 `POST /serve/prompts/add` |
| PUT | `/api/prompts/{id}` | 更新 Prompt | 通用 `PUT /serve/prompts/{id}` |
| DELETE | `/api/prompts/{id}` | 删除 Prompt | 通用 `POST /serve/prompts/delete` |

### 9. App 管理 — `/api/apps`

| 方法 | 路径 | 说明 | SDK/通用 |
|---|---|---|---|
| GET | `/api/apps` | 列出 App | SDK `list_app` |
| GET | `/api/apps/{id}` | 查看 App 详情 | SDK `get_app` |

### 10. 评估 — `/api/evaluate`

| 方法 | 路径 | 说明 | SDK |
|---|---|---|---|
| POST | `/api/evaluate` | 运行评估 | SDK `run_evaluation` |

## 四、实施计划

### 步骤 1：搭建骨架
- 创建 `core/` 和 `modules/` 目录
- 编写 `core/client.py`：Client 工厂单例
- 编写 `core/response.py`：统一响应格式

### 步骤 2：迁移现有代码
- 将 `qna_agent.py` 迁移到 `core/chat.py`，保留所有解析逻辑
- 更新 `app.py` 引用路径

### 步骤 3：实现各 module（按优先级）
1. `datasource.py` — 数据源管理（含类型列表、测试连接）
2. `knowledge.py` — 知识库管理
3. `connector.py` — MCP 连接器管理
4. `conversation.py` — 会话管理
5. `model.py` — 模型管理
6. `flow.py` — AWEL Flow 管理
7. `prompt.py` — Prompt 管理
8. `app.py`(module) — App 管理
9. `evaluation.py` — 评估管理

### 步骤 4：统一路由注册
- 在 `app.py` 中统一注册所有 module 的路由
- 添加 OpenAPI 文档标签分组

### 步骤 5：更新 Dockerfile + requirements + README

## 五、关键技术决策

### 1. 通用 serve API 调用封装
SDK 的 `Client` 类有 `get/post/put/delete` 方法，自动拼接 `/api/v2/serve` 前缀。对于 SDK 未封装的接口，统一封装一个轻量辅助方法：

```python
# core/client.py
class DbgptClient:
    _instance = None

    @classmethod
    def get_client(cls, api_base=None, api_key=None) -> Client:
        if cls._instance is None:
            cls._instance = Client(api_base=api_base, api_key=api_key, timeout=300)
        return cls._instance

    @staticmethod
    async def serve_get(client: Client, path: str, **params):
        """通用 serve GET"""
        resp = await client.get(path, **params)
        return resp.json()

    @staticmethod
    async def serve_post(client: Client, path: str, body: dict):
        """通用 serve POST"""
        resp = await client.post(path, body)
        return resp.json()
    # ... put, delete 类似
```

### 2. 保留现有问答核心不变
`QnAAgent` 的以下逻辑经过 CHASE 评测验证，保持不动：
- `normalize_mysql_sql()` — MySQL 双引号方言归一化
- `_parse_chart_view()` — chart-view 解析
- `_extract_plain()` — 纯文本提取
- 会话管理（每数据源独立会话）

### 3. 数据源路由表改为动态
现有 `DS_ROUTE` 硬编码了 4 个数据源，改为从 DB-GPT 动态查询：
- `/api/chat` 的 `ds` 参数直接用 DB-GPT 注册的数据源名
- 不再需要业务标识映射

## 六、与现有代码的关系

| 现有文件 | 处理方式 |
|---|---|
| `qna_agent.py` | 迁移到 `core/chat.py`，保留核心逻辑，删除 DS_ROUTE |
| `app.py` | 重写，统一注册所有 module 路由 |
| `requirements.txt` | 更新依赖 |
| `Dockerfile` / `docker-compose.yml` | 基本不变，可能调整环境变量 |
| `README.md` | 重写，完整接口文档 |

## 七、预计工作量

| 部分 | 接口数 | 复杂度 |
|---|---|---|
| 数据库管理 | 8 | 低（SDK+通用） |
| 知识库管理 | 12 | 中（SDK+通用） |
| MCP 连接器 | 10 | 中（全通用） |
| 会话管理 | 6 | 低（全通用） |
| 模型管理 | 4 | 低（全通用） |
| 问答 | 5 | 中（保留+增强） |
| AWEL Flow | 5 | 低（SDK） |
| Prompt 管理 | 4 | 低（全通用） |
| App 管理 | 2 | 低（SDK） |
| 评估 | 1 | 低（SDK） |
| **合计** | **57** | |
