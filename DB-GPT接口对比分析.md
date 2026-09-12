# DB-GPT 原生平台接口全量清单 & 与 qna_agent 能力对比

> 数据来源：DB-GPT OpenAPI (http://localhost:5670/openapi.json)，446KB，约 200+ 个接口

---

## 一、DB-GPT 平台接口全景

### 1. 对话核心（chat）

| # | 方法 | DB-GPT 接口 | 说明 | qna_agent 是否覆盖 |
|---|------|------------|------|:---:|
| 1 | POST | `/api/v1/chat/react-agent` | **React Agent 流式问答**（多步推理+SQL执行+结果返回） | ✅ `/ask/react-agent` |
| 2 | POST | `/api/v1/chat/knowledge-agent` | **知识库 Agent 流式问答**（纯知识库场景，无SQL/Shell工具） | ❌ **缺失** |
| 3 | POST | `/api/v1/chat/completions` | 通用对话补全（非流式） | ✅ `/ask`（SDK 封装） |
| 4 | POST | `/api/v2/chat/completions` | V2 通用对话补全 | ✅ `/ask`（SDK 封装） |
| 5 | POST | `/api/v1/chat/prepare` | 对话预处理（加载上下文/资源） | ❌ 未封装 |
| 6 | POST | `/api/v1/chat/topic/terminate` | **终止话题**（停止正在进行的对话） | ❌ **缺失** |
| 7 | POST | `/api/v1/chat/question/{id}/reject` | 拒绝反问 | ❌ 未封装 |
| 8 | POST | `/api/v1/chat/question/{id}/reply` | 回复反问 | ❌ 未封装 |
| 9 | POST | `/api/v1/chat/share` | **创建分享链接** | ❌ **缺失** |
| 10 | GET | `/api/v1/chat/share/{token}` | 获取分享内容 | ❌ **缺失** |
| 11 | DELETE | `/api/v1/chat/share/{token}` | 删除分享 | ❌ **缺失** |

### 2. 对话场景管理（dialogue/scenes）

| # | 方法 | DB-GPT 接口 | 说明 | qna_agent 是否覆盖 |
|---|------|------------|------|:---:|
| 12 | POST | `/api/v1/chat/dialogue/scenes` | **获取所有对话场景**（chat_data/chat_knowledge/chat_excel/chat_dashboard/chat_agent等） | ❌ **缺失** |
| 13 | POST | `/api/v1/chat/mode/params/list` | **获取场景参数列表**（根据chat_mode返回可选参数，如知识库列表/数据源列表） | ❌ **缺失** |
| 14 | POST | `/api/v1/chat/dialogue/new` | 新建会话 | ✅ `/conversations/new` |
| 15 | GET | `/api/v1/chat/dialogue/list` | **会话列表**（分页，含用户输入预览/模式/时间） | ✅ `/conversations/list` |
| 16 | GET | `/api/v1/chat/dialogue/messages/history` | **历史消息**（含完整对话上下文） | ✅ `/conversations/messages/history` |
| 17 | POST | `/api/v1/chat/dialogue/query` | 查询会话 | ❌ 未封装 |
| 18 | POST | `/api/v1/chat/dialogue/query_page` | 分页查询会话 | ✅ `/conversations/query_page` |
| 19 | POST | `/api/v1/chat/dialogue/delete` | 删除会话 | ✅ `/conversations/delete` |
| 20 | POST | `/api/v1/chat/dialogue/clear` | 清空会话 | ✅ `/conversations/clear` |
| 21 | GET | `/api/v1/chat/dialogue/export_messages` | **导出所有消息** | ❌ **缺失** |

### 3. 数据库管理（chat/db）

| # | 方法 | DB-GPT 接口 | 说明 | qna_agent 是否覆盖 |
|---|------|------------|------|:---:|
| 22 | GET | `/api/v1/chat/db/list` | **数据库列表**（前端用此接口） | ⚠️ 用 serve v2 替代 |
| 23 | GET | `/api/v1/chat/db/support/type` | **支持的数据库类型**（sqlite/mysql/postgresql/clickhouse/hive/tugraph/neo4j/spark/duckdb/doris/gaussdb等） | ⚠️ 用 serve v2 替代 |
| 24 | POST | `/api/v1/chat/db/add` | 添加数据库 | ⚠️ 用 serve v2 替代 |
| 25 | POST | `/api/v1/chat/db/delete` | 删除数据库 | ⚠️ 用 serve v2 替代 |
| 26 | POST | `/api/v1/chat/db/edit` | 编辑数据库 | ⚠️ 用 serve v2 替代 |
| 27 | POST | `/api/v1/chat/db/refresh` | **刷新数据库摘要**（重新分析表结构） | ❌ **缺失** |
| 28 | POST | `/api/v1/chat/db/summary` | **生成数据库摘要**（LLM自动分析表结构生成摘要） | ❌ **缺失** |
| 29 | POST | `/api/v1/chat/db/test/connect` | 测试连接 | ✅ `/datasources/test-connection` |

### 4. SQL 编辑器（editor）

| # | 方法 | DB-GPT 接口 | 说明 | qna_agent 是否覆盖 |
|---|------|------------|------|:---:|
| 30 | POST | `/api/v1/editor/sql/run` | **执行 SQL** | ❌ **缺失** |
| 31 | GET | `/api/v1/editor/sql` | **获取历史 SQL**（根据会话轮次） | ❌ **缺失** |
| 32 | GET | `/api/v1/editor/sql/rounds` | 获取 SQL 轮次 | ❌ 未封装 |
| 33 | GET | `/api/v1/editor/db/tables` | **获取数据库表结构树**（树形 DataNode） | ❌ **缺失** |
| 34 | POST | `/api/v1/editor/chart/run` | **执行图表** | ❌ 未封装 |
| 35 | POST | `/api/v1/editor/chart/info` | 获取图表信息 | ❌ 未封装 |
| 36 | GET | `/api/v1/editor/chart/list` | 图表列表 | ❌ 未封装 |

### 5. 知识库（knowledge）

| # | 方法 | DB-GPT 接口 | 说明 | qna_agent 是否覆盖 |
|---|------|------------|------|:---:|
| 37 | POST | `/api/v1/knowledge/space/add` | 添加知识空间 | ✅ `/knowledge/spaces` (v2) |
| 38 | POST | `/api/v1/knowledge/space/list` | 知识空间列表 | ✅ `/knowledge/spaces` (v2) |
| 39 | POST | `/api/v1/knowledge/space/delete` | 删除知识空间 | ✅ (v2) |
| 40 | GET | `/api/v1/knowledge/space/config` | 知识空间配置 | ❌ 未封装 |
| 41 | POST | `/api/v1/knowledge/{space}/document/add` | 添加文档 | ✅ (v2) |
| 42 | POST | `/api/v1/knowledge/{space}/document/list` | 文档列表 | ✅ (v2) |
| 43 | POST | `/api/v1/knowledge/{space}/document/sync` | 同步文档 | ✅ (v2) |
| 44 | POST | `/api/v1/knowledge/{space}/document/sync_batch` | 批量同步 | ⚠️ v2 有 batch_sync |
| 45 | POST | `/api/v1/knowledge/{space}/document/upload` | 上传文档 | ⚠️ v2 有 documents create |
| 46 | POST | `/api/v1/knowledge/{space}/chunk/list` | **Chunk 列表** | ❌ **缺失** |
| 47 | POST | `/api/v1/knowledge/{space}/chunk/edit` | **编辑 Chunk** | ❌ **缺失** |
| 48 | POST | `/api/v1/knowledge/{space_name}/recall_test` | **召回测试** | ❌ **缺失** |
| 49 | POST | `/api/v1/knowledge/{vector_name}/query` | **相似度查询** | ❌ **缺失** |
| 50 | POST | `/api/v1/knowledge/{space_id}/argument/save` | 参数保存 | ❌ 未封装 |
| 51 | POST | `/api/v1/knowledge/{space_id}/arguments` | 参数查询 | ❌ 未封装 |
| 52 | GET | `/api/v1/knowledge/{space_id}/recall_retrievers` | 召回器列表 | ❌ 未封装 |
| 53 | POST | `/api/v1/knowledge/{space_id}/build-graph` | **构建知识图谱** | ❌ **缺失** |
| 54 | POST | `/api/v1/knowledge/{space_id}/git/sync` | Git 仓库同步 | ❌ 未封装 |
| 55 | GET | `/api/v1/knowledge/{space_id}/git/sync-status` | Git 同步状态 | ❌ 未封装 |
| 56 | POST | `/api/v1/knowledge/{space_id}/git/incremental-sync` | 增量同步 | ❌ 未封装 |
| 57 | GET | `/api/v1/knowledge/{space_id}/stats` | **空间统计** | ❌ **缺失** |
| 58 | POST | `/api/v1/knowledge/document/summary` | 文档摘要 | ❌ 未封装 |
| 59 | GET | `/api/v1/knowledge/document/chunkstrategies` | Chunk 策略 | ❌ 未封装 |
| 60 | POST | `/api/v1/knowledge/retrieve_strategy_list` | 检索策略 | ❌ 未封装 |
| 61 | POST | `/api/v1/knowledge/{space_name}/graphvis` | 图谱可视化 | ❌ 未封装 |
| 62 | GET | `/api/v1/knowledge/{space_name}/codegraph/visualize` | 代码图可视化 | ❌ 未封装 |
| 63-69 | POST | `/api/v1/knowledge/{space_id}/tools/*` | KB 工具（cat/glob/grep/ls/semantic_search） | ❌ 未封装 |

### 6. 模型管理（model/worker）

| # | 方法 | DB-GPT 接口 | 说明 | qna_agent 是否覆盖 |
|---|------|------------|------|:---:|
| 70 | GET | `/api/v1/model/types` | 模型类型 | ✅ `/models/model-types` |
| 71 | GET | `/api/v1/model/supports` | 支持的模型 | ❌ **缺失** |
| 72 | GET | `/api/v2/serve/model/models` | 模型列表 | ✅ `/models/list` |
| 73 | POST | `/api/v2/serve/model/models` | 创建模型 | ❌ **缺失** |
| 74 | POST | `/api/v2/serve/model/models/start` | **启动模型** | ❌ **缺失** |
| 75 | POST | `/api/v2/serve/model/models/stop` | **停止模型** | ❌ **缺失** |
| 76 | POST | `/api/worker/generate` | 生成（非流式） | ❌ 未封装 |
| 77 | POST | `/api/worker/generate_stream` | 生成（流式） | ❌ 未封装 |
| 78 | POST | `/api/worker/embeddings` | **Embeddings** | ❌ **缺失** |
| 79 | POST | `/api/worker/count_token` | Token 计数 | ❌ 未封装 |
| 80 | GET | `/api/worker/parameter/descriptions` | 参数描述 | ❌ 未封装 |
| 81 | GET | `/api/worker/models/supports` | 支持的模型 | ❌ 未封装 |

### 7. AWEL Flow（serve/awel）

| # | 方法 | DB-GPT 接口 | 说明 | qna_agent 是否覆盖 |
|---|------|------------|------|:---:|
| 82 | GET | `/api/v2/serve/awel/flows` | Flow 列表 | ✅ `/flows` |
| 83 | POST | `/api/v2/serve/awel/flows` | 创建 Flow | ❌ 未封装 |
| 84 | PUT | `/api/v2/serve/awel/flows/{uid}` | 更新 Flow | ❌ 未封装 |
| 85 | DELETE | `/api/v2/serve/awel/flows/{uid}` | 删除 Flow | ❌ 未封装 |
| 86 | GET | `/api/v2/serve/awel/flows/{uid}` | Flow 详情 | ✅ `/flows/{uid}` |
| 87 | GET | `/api/v2/serve/awel/flow/templates` | **Flow 模板** | ❌ **缺失** |
| 88 | POST | `/api/v2/serve/awel/flow/debug` | **Flow 调试** | ❌ **缺失** |
| 89 | GET | `/api/v2/serve/awel/flow/export/{uid}` | **导出 Flow** | ❌ **缺失** |
| 90 | POST | `/api/v2/serve/awel/flow/import` | **导入 Flow** | ❌ **缺失** |
| 91 | GET | `/api/v2/serve/awel/nodes` | **节点列表** | ❌ **缺失** |
| 92 | POST | `/api/v2/serve/awel/nodes/refresh` | 刷新节点 | ❌ 未封装 |
| 93 | GET | `/api/v2/serve/awel/chat/flows` | **可对话的 Flow 列表** | ❌ **缺失** |
| 94-97 | POST/GET/PUT | `/api/v2/serve/awel/variables*` | **AWEL 变量管理** | ❌ 未封装 |

### 8. Prompt 管理

| # | 方法 | DB-GPT 接口 | 说明 | qna_agent 是否覆盖 |
|---|------|------------|------|:---:|
| 98 | POST | `/prompt/add` | 添加 | ✅ `/prompts/add` |
| 99 | POST | `/prompt/list` | 列表 | ✅ `/prompts/list` |
| 100 | POST | `/prompt/update` | 更新 | ✅ `/prompts/update` |
| 101 | POST | `/prompt/delete` | 删除 | ✅ `/prompts/delete` |
| 102 | POST | `/prompt/query_page` | 分页 | ✅ `/prompts/query_page` |
| 103 | POST | `/prompt/template/debug` | **模板调试** | ❌ **缺失** |
| 104 | POST | `/prompt/template/load` | **加载模板** | ❌ **缺失** |
| 105 | POST | `/prompt/response/verify` | **响应验证** | ❌ **缺失** |
| 106 | GET | `/prompt/type/targets` | 类型目标 | ✅ `/prompts/type/targets` |

### 9. App 管理

| # | 方法 | DB-GPT 接口 | 说明 | qna_agent 是否覆盖 |
|---|------|------------|------|:---:|
| 107 | POST | `/api/v1/app/list` | App 列表 | ✅ `/apps` (v2) |
| 108 | POST | `/api/v1/app/create` | 创建 App | ❌ **缺失** |
| 109 | POST | `/api/v1/app/detail` | App 详情 | ⚠️ v2 有 |
| 110 | POST | `/api/v1/app/edit` | 编辑 App | ❌ **缺失** |
| 111 | POST | `/api/v1/app/remove` | 删除 App | ❌ **缺失** |
| 112 | POST | `/api/v1/app/publish` | **发布 App** | ❌ **缺失** |
| 113 | POST | `/api/v1/app/unpublish` | **取消发布** | ❌ **缺失** |
| 114 | POST | `/api/v1/app/collect` | **收藏 App** | ❌ **缺失** |
| 115 | POST | `/api/v1/app/uncollect` | 取消收藏 | ❌ 未封装 |
| 116 | POST | `/api/v1/app/hot/list` | **热门 App** | ❌ **缺失** |
| 117 | GET | `/api/v1/app/resources/list` | App 资源 | ❌ 未封装 |
| 118 | POST | `/api/v1/app/native/init` | 初始化原生 App | ❌ 未封装 |
| 119 | GET | `/api/v1/app/export` | 导出 App | ❌ 未封装 |
| 120 | GET | `/api/v1/app/{code}` | 按 Code 查询 | ❌ 未封装 |
| 121 | POST | `/api/v1/app/admins/update` | 更新管理员 | ❌ 未封装 |

### 10. Agent 管理（v1/agent）

| # | 方法 | DB-GPT 接口 | 说明 | qna_agent 是否覆盖 |
|---|------|------------|------|:---:|
| 122 | POST | `/api/v1/agent/query` | Agent 列表 | ❌ **缺失** |
| 123 | POST | `/api/v1/agent/my` | 我的 Agent | ❌ **缺失** |
| 124 | POST | `/api/v1/agent/install` | 安装 Agent | ❌ 未封装 |
| 125 | POST | `/api/v1/agent/uninstall` | 卸载 Agent | ❌ 未封装 |
| 126 | POST | `/api/v1/agent/hub/update` | 插件中心更新 | ❌ 未封装 |
| 127 | POST | `/api/v1/agent/files` | 上传会话文件 | ❌ **缺失** |
| 128 | GET | `/api/v1/agent/files` | 列出会话文件 | ❌ **缺失** |
| 129 | GET | `/api/v1/agent/files/capabilities` | 文件能力 | ❌ 未封装 |
| 130-132 | GET/DELETE | `/api/v1/agent/files/*` | 文件操作（下载/预览/删除） | ❌ 未封装 |

### 11. 资源/文件管理（resource）

| # | 方法 | DB-GPT 接口 | 说明 | qna_agent 是否覆盖 |
|---|------|------------|------|:---:|
| 133 | POST | `/api/v1/resource/file/upload` | **上传文件**（关联到会话/对话模式） | ❌ **缺失** |
| 134 | POST | `/api/v1/resource/file/read` | **读取文件** | ❌ **缺失** |
| 135 | POST | `/api/v1/resource/file/delete` | 删除文件 | ❌ 未封装 |
| 136 | POST | `/api/v1/resource/params/list` | 资源参数 | ❌ 未封装 |

### 12. 反馈/评分（feedback）

| # | 方法 | DB-GPT 接口 | 说明 | qna_agent 是否覆盖 |
|---|------|------------|------|:---:|
| 137 | POST | `/api/v1/feedback/commit` | **提交反馈** | ❌ **缺失** |
| 138 | GET | `/api/v1/feedback/find` | **查询反馈** | ❌ **缺失** |
| 139 | GET | `/api/v1/feedback/select` | 反馈选项 | ❌ 未封装 |
| 140 | POST | `/api/v1/conv/feedback/add` | 添加对话反馈 | ❌ 未封装 |
| 141 | POST | `/api/v1/conv/feedback/cancel` | 取消反馈 | ❌ 未封装 |
| 142 | GET | `/api/v1/conv/feedback/reasons` | 反馈原因 | ❌ 未封装 |
| 143 | POST | `/api/v1/conv/feedback/update` | 更新反馈 | ❌ 未封装 |

### 13. 评估（evaluate）

| # | 方法 | DB-GPT 接口 | 说明 | qna_agent 是否覆盖 |
|---|------|------------|------|:---:|
| 144 | POST | `/api/v2/serve/evaluate/evaluation` | 执行评估 | ✅ `/evaluation/run` |
| 145 | GET | `/api/v2/serve/evaluate/benchmark_task_list` | 基准任务列表 | ❌ 未封装 |
| 146 | GET | `/api/v2/serve/evaluate/scenes` | 评估场景 | ❌ 未封装 |
| 147-152 | GET | `/api/v2/serve/evaluate/benchmark/*` | 基准数据集/结果 | ❌ 未封装 |

### 14. 定时任务（scheduled-tasks）

| # | 方法 | DB-GPT 接口 | 说明 | qna_agent 是否覆盖 |
|---|------|------------|------|:---:|
| 153 | POST | `/api/v2/serve/scheduled-tasks/` | 创建定时任务 | ❌ **缺失** |
| 154 | GET | `/api/v2/serve/scheduled-tasks/` | 任务列表 | ❌ 未封装 |
| 155 | PUT | `/api/v2/serve/scheduled-tasks/{id}` | 更新任务 | ❌ 未封装 |
| 156 | DELETE | `/api/v2/serve/scheduled-tasks/{id}` | 删除任务 | ❌ 未封装 |
| 157 | GET | `/api/v2/serve/scheduled-tasks/{id}/runs` | 运行历史 | ❌ 未封装 |
| 158 | POST | `/api/v2/serve/scheduled-tasks/{id}/toggle` | 启停任务 | ❌ 未封装 |

### 15. 其他

| # | 方法 | DB-GPT 接口 | 说明 | qna_agent 是否覆盖 |
|---|------|------------|------|:---:|
| 159 | POST | `/api/v1/sql/editor/submit` | SQL 编辑器提交 | ❌ 未封装 |
| 160 | POST | `/api/v1/examples/use` | 使用示例文件 | ❌ 未封装 |
| 161 | GET | `/api/v1/permission/db/list` | 权限数据库列表 | ❌ 未封装 |
| 162 | GET | `/api/v1/team-mode/list` | 团队模式列表 | ❌ 未封装 |
| 163 | GET | `/api/v1/resource-type/list` | 资源类型列表 | ❌ 未封装 |
| 164 | GET | `/api/v1/native_scenes` | 原生场景 | ❌ 未封装 |
| 165 | GET | `/api/v1/llm-strategy/list` | LLM 策略 | ❌ 未封装 |
| 166 | GET | `/api/v1/skills/list` | Skills 列表 | ❌ 未封装 |
| 167 | GET | `/api/v1/skills/detail` | Skill 详情 | ❌ 未封装 |
| 168 | POST | `/api/v1/skills/import_github` | 从 GitHub 导入 Skill | ❌ 未封装 |
| 169 | POST | `/api/v1/skills/upload` | 上传 Skill | ❌ 未封装 |
| 170 | GET | `/api/v1/dbgpts/list` | DBGPTs 列表 | ❌ 未封装 |
| 171-176 | * | `/api/v1/serve/dbgpts/*` | Hub/My DBGPTs 管理 | ❌ 未封装 |
| 177-180 | * | `/api/v2/serve/file/*` | 文件存储服务 | ❌ 未封装 |

---

## 二、DB-GPT 原生对话场景清单

通过 `/api/v1/chat/dialogue/scenes` 获取，DB-GPT 支持 **6 种对话场景**：

| chat_scene | scene_name | 说明 | qna_agent chat_mode | 差距 |
|------------|-----------|------|---------------------|------|
| `chat_with_db_execute` | Chat Data | 自然语言→SQL→执行→结果 | `chat_data`（SDK）/ `react_agent`（新） | ✅ react_agent 可用 |
| `chat_with_db_qa` | Chat DB | 与元数据对话（不执行SQL） | `chat_with_db_qa`（枚举有但前端未映射） | ⚠️ 前端缺少按钮 |
| `chat_excel` | Chat Excel | **对话Excel文件** | ❌ 完全缺失 | 需新增 |
| `chat_knowledge` | Chat Knowledge | 知识库对话 | `chat_knowledge` + `react_agent` | ✅ |
| `chat_dashboard` | Dashboard | 仪表盘分析 | `chat_dashboard`（枚举有但前端未映射） | ⚠️ 前端缺少按钮 |
| `chat_agent` | Agent Chat | **插件Agent对话** | ❌ 完全缺失 | 需新增 |

此外 DB-GPT 还有两个 v1 chat 接口：
- `/api/v1/chat/react-agent` — React Agent（多步推理，已封装）
- `/api/v1/chat/knowledge-agent` — Knowledge Agent（纯知识库，**未封装**）

---

## 三、关键能力差距分析

### 🔴 P0 — 影响核心问答体验

| 差距 | 影响 | 修复方案 |
|------|------|---------|
| **knowledge-agent 接口** | 知识库问答不如原生平台（缺少多步检索+引用） | 新增 `/ask/knowledge-agent` SSE 接口 |
| **chat_excel 场景** | 无法对话 Excel 文件 | 新增文件上传 + chat_excel 模式 |
| **chat_agent 场景** | 无法使用 Agent/插件对话 | 新增 chat_agent 模式 |
| **dialogue/scenes 接口** | 前端模式按钮硬编码，无法动态适配 | 前端调用 scenes API 动态生成模式选择器 |
| **mode/params/list 接口** | 前端参数下拉框数据源不完整 | 前端调用此接口动态获取参数选项 |

### 🟡 P1 — 提升用户体验

| 差距 | 影响 | 修复方案 |
|------|------|---------|
| **话题终止** | 无法停止正在进行的对话 | 封装 `/api/v1/chat/topic/terminate` |
| **会话历史导出** | 无法导出对话记录 | 封装 `/api/v1/chat/dialogue/export_messages` |
| **分享链接** | 无法分享对话 | 封装 chat/share 接口 |
| **文件上传** | 无法上传文件到对话 | 封装 resource/file/upload |
| **DB摘要/刷新** | 数据库表结构摘要不会自动更新 | 封装 chat/db/summary + refresh |
| **表结构树** | 无法查看数据库表结构 | 封装 editor/db/tables |
| **SQL执行** | 无法独立执行SQL | 封装 editor/sql/run |
| **反馈/评分** | 无法对回答评分 | 封装 feedback 接口 |
| **模型启停** | 无法启动/停止模型 | 封装 model/models/start + stop |

### 🟢 P2 — 管理功能增强

| 差距 | 影响 |
|------|------|
| Flow CRUD（创建/编辑/删除/导入/导出/调试） | 无法可视化编辑 Flow |
| App CRUD（创建/编辑/发布/删除） | 无法管理应用 |
| 定时任务 | 无法调度定时任务 |
| 知识库高级功能（Chunk编辑/召回测试/图谱构建/统计） | 知识库管理能力有限 |
| AWEL 变量管理 | 无法管理 Flow 变量 |
| Skills 管理 | 无法管理 Skills |
| DBGPTs Hub | 无法浏览/安装社区资源 |

---

## 四、建议优先实施清单

### 第一批：补齐问答体验（P0）

1. **新增 knowledge-agent 接口** — `/ask/knowledge-agent`，调用 DB-GPT `/api/v1/chat/knowledge-agent`
2. **前端动态场景** — 调用 `/api/v1/chat/dialogue/scenes` 动态渲染模式按钮
3. **前端动态参数** — 调用 `/api/v1/chat/mode/params/list` 填充参数下拉
4. **新增 chat_excel** — 文件上传 + Excel 对话
5. **新增 chat_agent** — Agent/插件对话

### 第二批：提升交互（P1）

6. **话题终止** — 停止正在进行的对话
7. **会话导出** — 导出对话记录
8. **分享链接** — 分享对话
9. **文件上传** — 上传文件到会话
10. **DB摘要刷新** — 刷新表结构摘要
11. **表结构树** — 树形展示表/字段
12. **SQL执行** — 独立 SQL 编辑器
13. **反馈评分** — 对话评分
14. **模型启停** — 启动/停止模型

### 第三批：管理增强（P2）

15. Flow CRUD + 模板 + 导入导出
16. App CRUD + 发布
17. 定时任务管理
18. 知识库高级功能
19. AWEL 变量
20. Skills 管理
