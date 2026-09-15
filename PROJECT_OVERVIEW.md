# 智能问数 Agent（qna-agent）项目概况

> 更新时间：2026-09-15 15:20
> 用途：新会话交接文档。优化其他功能前请先通读本文。

---

## 一、项目定位

基于 **DB-GPT SDK 封装**的自定义智能问数 Agent，提供统一的问答、数据源、知识库、模型管理服务。相比 DB-GPT 原生前端，qna-agent 有自己的界面和业务逻辑（应用管理、会话隔离、模型自助配置等）。

## 二、代码仓库与部署

| 项 | 值 |
|---|---|
| 代码路径 | `F:\workspace_mine\WorkBuddy\智能问数anget\qna_agent\` |
| Git remote | https://github.com/BigZhouxc/DB-GPT2.git （master 分支） |
| 最新提交 | `376e162` feat: 模型全面数据库化 + 模型管理增强 + 应用创建修复 |
| 推送方式 | 直接 `git push origin master`；**先执行** `git config http.postBuffer 524288000`（否则大推送会 disconnect），网络抖动重试即可 |
| 容器 | `qna-agent`（端口 8080），`db-gpt-webserver-1`（DB-GPT 后端 5670），`db-gpt-db-1`（MySQL，root/aa123456） |
| 改代码生效 | `docker cp <文件> qna-agent:/app/... && docker restart qna-agent`（秒级） |

## 三、整体架构

```
浏览器 → qna-agent (8080, FastAPI + static/app.js)
              │  core/client_factory.py → DB-GPT SDK / HTTP
              ▼
       db-gpt-webserver-1 (5670, DB-GPT)
              │  proxy/openai 客户端
              ▼
       host nginx (9876) → https://onerouter.cmaiot.cn (LLM 网关)
```

- 后端入口：`app.py`（FastAPI），`modules/` 按领域分路由：app/model/qa/conversation/datasource/knowledge/connector/evaluation/file/flow/prompt
- 前端：`static/index.html + app.js + style.css`（无框架原生 JS）
- 部署配置：`deploy/dbgpt-custom-mysql.toml`

## 四、模型管理（DB-only 模式，已落地）

- **所有模型配置存 MySQL** `dbgpt` 库 `dbgpt_serve_model` 表，TOML 中无任何模型定义（只有 `default_llm`/`default_embedding` 字符串）
- webserver 重启后自动从 DB 恢复模型（已验证）
- **关键补丁**（本地修改，未上游）：`DB-GPT/packages/dbgpt-core/src/dbgpt/model/cluster/worker/manager.py` 中 `initialize_worker_manager_in_client` 无条件创建 `LocalWorkerManager`——否则 TOML 无 LLM 时启动崩溃（`'NoneType' has no attribute 'after_start'`）
- 界面功能：添加 / 编辑（含 api_base、api_key）/ 删除 / 停止 / **真实推理连通性测试**
- 当前注册模型：`TS/GLM-5.2`（proxy/openai，api_base = nginx 9876 代理）

## 五、必须知道的网络与格式约束（踩坑实录）

1. **容器网络差异**：
   - `qna-agent` 容器有代理（host 7897）→ 可直连外网
   - `db-gpt-webserver-1` 无代理 → 直连 onerouter **必超时**
   - 结论：模型 api_base 必须填 `http://host.docker.internal:9876/v1`（nginx 代理）
2. **worker /generate 消息角色**：必须小写 `human`/`ai`/`system`。用 `user` 或 `HUMAN` 会被 `to_common_messages()` **静默丢弃** → 空 messages → 上游 502（带"服务暂时不可用"字样的假故障）
3. **推理模型 token 预算**：DeepSeek-V4 类模型的思考过程消耗 `max_tokens`，测试时预算给 512+，否则回复为空
4. **连通性测试的教训**：只查实例存活（model_metadata）是假测试；现版本已改为真实推理测试（默认走 worker 全链路，编辑弹窗传 api_base/api_key 时直测端点）
5. **NativeTeamContext 校验**：`gpts_app.team_context` 必须含 `scene_name` 键（值为 None 也行，键必须存在），否则应用加载报 pydantic ValidationError。qna-agent 创建/编辑应用时会自动带上
6. **api_base 规范化**：`normalize_api_base()` 容忍用户粘贴完整 `/v1/chat/completions`（自动截断到 `/v1`）

## 六、测试数据集（NL2SQL 评测）

- `test-datasets/`：retail_company（11 表 20120 行，25 题）、chinook、knowledgebase
- CHASE 基准：`test-datasets/chase/`（350 个 SQLite），已选 3 库 60 题：游戏（简单）/水果（中等）/双11活动（困难）
- 题目：`test-datasets/test_questions_final.json`；指南：`test-datasets/DB-GPT测试指南.md`
- Docker 已挂载 `../test-datasets:/app/test-datasets`
- 对比结果：`对比结果/chase_review_mysql.md`、`chase_review_platform.md`

## 七、启动与运维

- 一键启动：`启动DB-GPT.bat`（含 webserver、MySQL、前端 dbgpt-frontend:3000、qna-agent）
- nginx（9876 LLM 代理）启动命令见 `MEMORY.md`（Git Bash 下需清代理环境变量 + cmd start /B）
- 数据源注册注意：SQLite 数据源 API body 用 `file_path` 字段（不是 `db_path`）

## 八、近期完成的工作（本次会话）

1. 模型界面交互重构：去掉与"添加模型"冲突的启动按钮；编辑弹窗支持 api_base/api_key/provider；新增删除、停止、连通性测试
2. **模型全面数据库化**：清空 6 个旧模型 → 注册唯一模型 → 重启自动恢复验证通过
3. 修复 DB-GPT 零模型启动崩溃（manager.py 补丁）
4. 连通性测试重写为真实推理测试（修复"测试通过但对话超时"的假象）
5. 修复应用对话报错：GLM-5.2 api_base 改走 nginx 代理 + team_context 补 scene_name（含 6 个存量应用批量回填）

## 九、已知待优化方向（供新会话参考）

- 前端 app.js 较大，可考虑模块化拆分
- 会话/消息渲染的流式体验可继续打磨（SSE 已通）
- 模型测试目前是同步阻塞（最长 90s），可改为后台任务+轮询
- DB-GPT 补丁（manager.py）尚在本地包内，升级 DB-GPT 版本时需重新套用
- 知识库/数据源模块尚未深度定制，按需迭代

## 十、环境约定（必须遵守）

- Python 包安装用 conda 环境 `workbuddy`
- 服务生命周期一律走 Docker（docker start/stop/restart），不本地直启
- 交流用中文，输出偏好结构化 + 精确数据
- 项目历史与踩坑记录：`.workbuddy/memory/2026-09-15.md`（当日全量日志）、`.workbuddy/memory/MEMORY.md`（长期记忆）
