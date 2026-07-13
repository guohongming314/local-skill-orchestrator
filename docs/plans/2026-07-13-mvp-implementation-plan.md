# 当前交付目标开发实施计划

**日期：** 2026-07-13  
**状态：** Ready for implementation

## 实施目标

交付一个本地优先的 Codex 项目能力初始化器，当前验收范围支持：

- 分析空白目录和已有仓库。
- 盘点本地 Skills、Tools、MCP 和 Plugins。
- 通过 Codex 对话确认项目目标。
- 生成结构化 Blueprint。
- 使用 Practice Packs 生成能力需求。
- 优先解析本地能力。
- 生成项目级配置、规则和 Skill。
- 针对开发任务生成工作流和 Context Capsule。
- 使用 Doctor 检查配置和漂移。

## 实施约束

- 使用 Python 3.12+。
- 当前验收范围只支持 Codex。
- 外部能力只读扫描。
- 不自动远程搜索或安装。
- 不自建 Agent Loop。
- 所有项目写入先经过 Dry-run。
- 所有配置必须有 Schema 和测试。

## Step 1：初始化工程

### 创建

- `pyproject.toml`
- `uv.lock`
- `src/vibe/__init__.py`
- `src/vibe/__main__.py`
- `src/vibe/cli.py`
- `src/vibe/commands/`
- `tests/`
- `.gitignore`

### 依赖

- Typer。
- Rich 和 prompt_toolkit。
- Pydantic 和 jsonschema。
- ruamel.yaml。
- SQLAlchemy 和 Alembic。
- LangGraph。
- AnyIO。
- MCP Python SDK。
- pytest、pytest-asyncio 和 Hypothesis。
- Ruff 和 mypy。

### 验证

- `uv sync`。
- `uv run ruff check .`。
- `uv run mypy src`。
- `uv run pytest`。
- `vibe --help`。

## Step 2：定义核心 Schema

### 创建

- `src/vibe/models/blueprint.py`
- `src/vibe/models/capability.py`
- `src/vibe/models/resolution.py`
- `src/vibe/models/capsule.py`
- `src/vibe/models/repository.py`
- `src/vibe/models/task.py`

### 要求

- 使用 Pydantic Model 作为类型和验证事实来源。
- 导出 JSON Schema。
- 拒绝未知危险字段。
- 提供 Schema 版本。
- 提供迁移接口占位。

### 测试

- 合法最小 Fixture。
- 合法完整 Fixture。
- 缺失必填字段。
- 未知版本。
- 权限字段非法。
- Capsule 缺少来源摘要。

## Step 3：实现本地状态存储

### 创建

- `src/vibe/persistence/database.py`
- `src/vibe/persistence/models.py`
- `src/vibe/persistence/repositories.py`
- `src/vibe/persistence/migrations/`
- `alembic.ini`

### 数据表

- `runs`
- `codex_threads`
- `inventory_cache`
- `capability_verifications`
- `user_trust_decisions`

### 测试

- SQLAlchemy Model 和数据库映射。
- Alembic 初始迁移。
- 升级和降级迁移测试。
- Run 创建和恢复。
- 不保存 Secret 字段。

## Step 4：Codex app-server Spike

### 创建

- `src/vibe/codex/app_server.py`
- `src/vibe/codex/jsonrpc.py`
- `src/vibe/codex/protocol.py`
- `src/vibe/codex/events.py`
- `src/vibe/codex/approvals.py`
- `src/vibe/codex/exec_fallback.py`
- `src/vibe/commands/spike_codex.py`
- `tests/integration/test_codex_app_server.py`

### 验证项

- 启动和初始化 `codex app-server`。
- 创建 Thread 并连续运行两轮 Turn。
- 处理 Server Notification 和 Server Request。
- 处理命令、文件修改和动态工具审批。
- 保存和恢复 Thread ID。
- 捕获中断、超时和子进程崩溃。
- 生成 Codex Protocol JSON Schema。
- 最终输出 JSON 并通过 Pydantic 验证。
- 验证失败后修复一次。
- 验证 `codex exec --json --output-schema` 回退。

### 决策输出

记录 ADR：

- app-server JSON-RPC 生命周期。
- 协议版本和 Schema 兼容策略。
- 结构化结果方案。
- 用户认证方式。
- 测试中如何使用 Fake app-server Process。

## Step 5：仓库扫描

### 创建

- `src/vibe/inspect/repository.py`
- `src/vibe/inspect/git.py`
- `src/vibe/inspect/stack.py`
- `src/vibe/inspect/commands.py`
- `src/vibe/inspect/instructions.py`
- `src/vibe/commands/inspect.py`

### 首批识别

- Git。
- Node、Python、Rust、Go。
- npm、pnpm、yarn、bun。
- 常见构建和测试脚本。
- GitHub Actions。
- Docker 和 Dev Container。
- 数据库迁移目录。
- Agent 指令文件。

### 测试 Fixture

- 空白目录。
- 单包 Node 项目。
- pnpm Monorepo。
- Python 项目。
- Rust 项目。
- 多种包管理器冲突。
- 未提交修改。

## Step 6：本地能力 Inventory

### 创建

- `src/vibe/inventory/service.py`
- `src/vibe/inventory/adapters/base.py`
- `src/vibe/inventory/adapters/agent_skill.py`
- `src/vibe/inventory/adapters/cli_tool.py`
- `src/vibe/inventory/adapters/codex_mcp.py`
- `src/vibe/inventory/adapters/codex_plugin.py`
- `src/vibe/commands/capabilities.py`

### 行为

- 扫描项目级和用户级 Skills。
- 解析 Skill Frontmatter。
- 识别依赖文件和脚本。
- 检测 Tool 版本。
- 读取 MCP 和 Plugin 元数据。
- 规范化 Manifest。
- 运行只读验证。

### 测试

- 正常 Skill。
- 损坏 Frontmatter。
- 名称和目录不一致。
- 依赖 Tool 缺失。
- 重复能力。
- 本地复合能力。

## Step 7：初始化状态机

### 创建

- `src/vibe/workflows/init_graph.py`
- `src/vibe/workflows/state.py`
- `src/vibe/workflows/checkpoints.py`

### 状态

- Inspect。
- Inventory。
- Interview。
- Model。
- Resolve。
- Review。
- Apply。
- Verify。

### 测试

- 正常路径。
- 用户取消。
- Interview 恢复。
- Codex 失败后重试。
- 写入失败回滚。
- LangGraph Checkpoint 恢复。

## Step 8：项目初始化访谈

### 创建

- `src/vibe/conversation/interview.py`
- `src/vibe/conversation/prompts.py`
- `src/vibe/conversation/structured_result.py`
- `src/vibe/commands/init.py`

### 输入

- Repository Snapshot。
- Unknown 和 Conflict。
- Local Inventory 摘要。
- 用户级偏好。

### 输出

- Project Model。
- Risk Model。
- Constraints。
- Preferences。
- Locked Decisions。

### 测试

- 已有仓库。
- 空白目录。
- 用户不了解工具名称。
- 用户改变答案。
- 用户拒绝建议。
- 用户锁定技术栈。

## Step 9：Practice Pack 引擎

### 创建

- `practice-packs/base-engineering/`
- `practice-packs/web-application/`
- `practice-packs/backend-api/`
- `practice-packs/security-sensitive/`
- `src/vibe/practices/loader.py`
- `src/vibe/practices/matcher.py`
- `src/vibe/practices/evaluator.py`

### 测试

- 条件匹配。
- 强度合并。
- 用户覆盖。
- 例外匹配。
- 多 Pack 冲突。
- 不适用 Practice 不进入结果。

## Step 10：本地能力解析器

### 创建

- `src/vibe/resolver/requirements.py`
- `src/vibe/resolver/policy.py`
- `src/vibe/resolver/scoring.py`
- `src/vibe/resolver/local.py`

### 行为

- 从 Project Model 生成能力需求。
- 应用硬过滤。
- 计算 Fit、Trust 和 Risk。
- 优先本地能力。
- 允许零个额外能力。
- 输出 Gap。
- 输出选中、拒绝和延后理由。

### 测试

- 小项目不推荐 CodeGraph。
- 大型 Monorepo 使用本地 CodeGraph。
- 短期项目不推荐 Claude-Mem。
- 长期项目将 Claude-Mem 标记为可选。
- Tool 可以替代 MCP。
- 高权限能力被策略过滤。

## Step 11：项目文件生成

### 创建

- `src/vibe/materialize/changeset.py`
- `src/vibe/materialize/ownership.py`
- `src/vibe/materialize/writer.py`
- `src/vibe/materialize/templates.py`
- `templates/`

### 生成

- `AGENTS.md`。
- `.ai-project/*`。
- 项目级 Skill。
- Capability Lockfile。

### 测试

- Dry-run 不写入。
- Owned 文件重复生成一致。
- 已有 `AGENTS.md` 不被覆盖。
- Managed 区块更新。
- 写入前文件变化导致中止。
- 写入失败回滚。

## Step 12：Doctor 和 Drift

### 创建

- `src/vibe/doctor/checks.py`
- `src/vibe/doctor/report.py`
- `src/vibe/compiler/invalidation.py`
- `src/vibe/commands/doctor.py`
- `src/vibe/commands/diff.py`

### 检查

- Schema。
- 能力存在性。
- 命令存在性。
- 摘要变化。
- 权限变化。
- 技术栈漂移。
- 生成文件漂移。
- Capsule 失效。

## Step 13：任务场景和风险模型

### 创建

- `src/vibe/workflows/scenarios.py`
- `src/vibe/workflows/task_graph.py`
- `src/vibe/workflows/phases.py`
- `src/vibe/models/task.py`
- `src/vibe/models/risk.py`

### 首批场景

- Bug。
- Feature。
- Refactor。
- Security。
- Migration。
- Review。

其余场景在同一 Registry 上扩展。

### 测试

- 简单 UI Bug 使用 Fast。
- 支付 Bug 使用 Rigorous。
- 只读 Review 不获得写权限。
- 技术探索不误判为生产实现。

## Step 14：Context Compiler

### 创建

- `src/vibe/compiler/intent.py`
- `src/vibe/compiler/context.py`
- `src/vibe/commands/plan.py`

### 行为

- 解析任务意图和范围。
- 选择工作流模式。
- 绑定当前阶段能力。
- 生成 Context Capsule。
- 设置 Token 预算。
- 设置来源摘要和失效条件。
- 阶段变化时重编译。

### 测试

- README 修改选择零额外能力。
- 跨模块 Bug 选择代码关系分析。
- 记忆结果只作为线索。
- 无关 Skill 不进入 Capsule。
- Git HEAD 变化导致失效。
- 用户改变范围导致重编译。

## Step 15：生成 Bootstrap Skill 和项目 Skill

### 创建

- `bootstrap-skill/SKILL.md`
- `bootstrap-skill/agents/openai.yaml`
- 项目 Skill 模板。
- Skill 验证测试。

### Bootstrap Skill 职责

- 引导用户运行初始化。
- 解释 Blueprint 和能力计划。
- 调用 CLI 完成确定性扫描和生成。
- 不复制 CLI 的策略逻辑。

### Project Skill 职责

- 读取项目工作流。
- 识别当前任务场景。
- 使用 Context Capsule。
- 执行软路由。
- 缺少能力时报告 Gap。

## Step 16：端到端评测

### 创建

- `tests/scenarios/init/`
- `tests/scenarios/tasks/`
- `tests/e2e/`
- `tests/results-template.md`

### 场景

- 空白项目初始化。
- 已有小型项目。
- 大型 Monorepo。
- 无任何 Skill 的环境。
- 本地存在 CodeGraph。
- 本地存在 Claude-Mem。
- 能力冲突。
- 用户拒绝推荐。
- 简单任务零能力。
- 高风险任务严格流程。

### 发布门禁

- 单元测试通过。
- Fixture 测试通过。
- Schema 兼容性测试通过。
- Skill 校验通过。
- `git diff --check` 通过。
- 核心场景人工审阅通过。

## 目标与工作项映射

### 目标一：建立可靠控制面

Step 1–7。完成工程基础、Codex 技术路径、确定性仓库分析和本地能力盘点后统一验收。

### 目标二：完成项目初始化闭环

Step 8–12。以 `vibe init`、安全 Dry-run、可复现配置和 Doctor 结果统一验收。

### 目标三：完成任务编排并达到发布标准

Step 13–16。以真实任务的风险匹配、Context Capsule 质量和发布门禁统一验收。

## 开始编码前的最终检查

- 产品范围已经明确。
- 当前验收范围和后续能力方向边界明确。
- 主要开源依赖已经确定。
- Codex 运行入口有官方 SDK 和 CLI 回退方案。
- 安全、隐私和权限边界明确。
- 数据结构和生成文件明确。
- 工作流和任务场景可以扩展。
- 有评测计划。

没有剩余的产品级阻塞问题，可以开始“建立可靠控制面”目标的实现。
