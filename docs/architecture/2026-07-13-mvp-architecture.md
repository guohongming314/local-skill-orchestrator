# MVP 技术架构

**日期：** 2026-07-13  
**状态：** Python 开发基线

## 架构目标

第一版构建一个本地 Python CLI，通过 Codex `app-server` 的 JSON-RPC 协议完成线程、对话、事件、审批和动态工具交互，通过确定性 Python 模块完成扫描、权限、解析、写入和验证。

第一版不自建模型推理服务，不直接调用通用模型 API，不自动安装远程能力。Codex 仍然是实际编码执行者，Python 系统负责控制面、能力治理和上下文编译。

## 为什么选择 Python

本产品的长期复杂度主要来自：

- 结构化项目建模。
- 动态工作流和人工审批。
- 能力解析和策略评估。
- 本地检索、评测和数据分析。
- 安全扫描和供应链分析。
- 后续可能出现的远程服务和组织治理。

Python 在数据模型、Agent Workflow、评测、检索、安全工具和服务端演进方面具有更完整的生态。Codex `app-server` 使用语言无关 JSON-RPC，因此不需要为了使用 TypeScript SDK 将整个控制面绑定到 TypeScript。

## 技术栈

```text
语言              Python 3.12+
项目和依赖管理    uv
CLI               Typer
终端呈现          Rich
交互输入          prompt_toolkit
异步运行时        AnyIO
Codex              codex app-server JSON-RPC
工作流            LangGraph
数据模型          Pydantic v2
JSON Schema       Pydantic JSON Schema + jsonschema
YAML               ruamel.yaml
本地数据库        SQLite
ORM               SQLAlchemy 2
数据库迁移        Alembic
文本检索          SQLite FTS5
Skill             Agent Skills Specification
MCP               官方 MCP Python SDK
测试              pytest + pytest-asyncio + Hypothesis
静态检查          Ruff + mypy
```

## 不采用的核心方案

- 不使用 TypeScript Codex SDK 作为架构基础。
- 不通过解析 Codex 终端文本实现集成。
- 不自研状态机和持久化框架。
- 不自研 ORM、数据库迁移和 Schema 系统。
- 不将 Pydantic AI 作为第一版 Agent Runtime。
- 不同时使用 LangGraph 和另一套主工作流引擎。

## 仓库结构

第一版保持单个 Python Package，使用 `src` Layout。

```text
local-skill-orchestrator/
├── pyproject.toml
├── uv.lock
├── src/
│   └── vibe/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       ├── commands/
│       │   ├── init.py
│       │   ├── inspect.py
│       │   ├── doctor.py
│       │   ├── diff.py
│       │   ├── plan.py
│       │   └── capabilities.py
│       ├── models/
│       │   ├── blueprint.py
│       │   ├── capability.py
│       │   ├── repository.py
│       │   ├── resolution.py
│       │   ├── task.py
│       │   ├── risk.py
│       │   └── capsule.py
│       ├── codex/
│       │   ├── app_server.py
│       │   ├── jsonrpc.py
│       │   ├── protocol.py
│       │   ├── events.py
│       │   ├── approvals.py
│       │   └── exec_fallback.py
│       ├── inspect/
│       │   ├── repository.py
│       │   ├── git.py
│       │   ├── commands.py
│       │   ├── stack.py
│       │   └── instructions.py
│       ├── inventory/
│       │   ├── service.py
│       │   └── adapters/
│       │       ├── base.py
│       │       ├── agent_skill.py
│       │       ├── cli_tool.py
│       │       ├── codex_mcp.py
│       │       ├── codex_plugin.py
│       │       └── codex_hook.py
│       ├── conversation/
│       │   ├── interview.py
│       │   ├── prompts.py
│       │   └── structured_result.py
│       ├── practices/
│       │   ├── loader.py
│       │   ├── matcher.py
│       │   └── evaluator.py
│       ├── resolver/
│       │   ├── requirements.py
│       │   ├── local.py
│       │   ├── policy.py
│       │   └── scoring.py
│       ├── workflows/
│       │   ├── init_graph.py
│       │   ├── task_graph.py
│       │   ├── scenarios.py
│       │   └── phases.py
│       ├── compiler/
│       │   ├── intent.py
│       │   ├── context.py
│       │   └── invalidation.py
│       ├── materialize/
│       │   ├── changeset.py
│       │   ├── ownership.py
│       │   ├── writer.py
│       │   └── templates.py
│       ├── doctor/
│       │   ├── checks.py
│       │   └── report.py
│       ├── persistence/
│       │   ├── database.py
│       │   ├── models.py
│       │   ├── repositories.py
│       │   └── migrations/
│       └── security/
│           ├── permissions.py
│           ├── redaction.py
│           └── trust.py
├── practice-packs/
├── templates/
├── bootstrap-skill/
│   ├── SKILL.md
│   └── agents/openai.yaml
├── tests/
│   ├── fixtures/
│   ├── scenarios/
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── alembic.ini
└── docs/
```

## Codex 集成架构

### 为什么使用 `codex app-server`

`app-server` 是 Codex 的双向 JSON-RPC API，提供：

- Thread 创建、恢复和归档。
- Turn 启动、中断和事件流。
- 命令执行和文件修改审批。
- 动态工具调用。
- MCP 状态读取。
- 配置读取。
- Skill 列表和变更通知。
- JSON Schema 生成。

它比反复启动 `codex exec` 更适合多轮对话、实时事件、审批和长期运行状态。

### 进程模型

```text
vibe Python Process
├── Typer CLI
├── LangGraph Control Plane
├── CodexAppServerClient
│   └── subprocess: codex app-server --listen stdio://
└── SQLite
```

Python 使用 AnyIO 启动和管理 `codex app-server` 子进程，通过 stdin/stdout 交换 JSON Lines。

### JSON-RPC Client

客户端需要支持：

- Request ID 和 Pending Future 映射。
- Server Notification。
- Server Request 和双向响应。
- 超时和取消。
- 子进程异常退出。
- stderr 独立日志。
- 协议版本初始化。
- 未知事件向前兼容。

不得把 stdout 日志和 JSON-RPC 消息混合处理。

### 协议模型

开发和 CI 中执行：

```bash
codex app-server generate-json-schema --out generated/codex-schema
```

使用生成 Schema：

- 验证当前 Codex 版本协议。
- 生成或更新 Python Protocol Models。
- 检测 Codex 协议漂移。
- 保留未知字段，避免小版本变化导致完全失败。

内部业务层不直接依赖完整 Codex Protocol Model，而通过稳定的 Gateway Interface 使用必要能力。

### `codex exec` 回退

`codex exec --json --output-schema` 仅用于：

- `app-server` 不可用时的诊断。
- 无交互批处理。
- CI 中的结构化提取验证。
- 协议 Spike 对比。

它不是主交互架构。

## 运行入口

### `vibe init`

```text
CLI 启动
-> 加载项目策略
-> 确定性 Inspect
-> 本地 Inventory
-> 启动 Codex app-server
-> 初始化 Client
-> 创建或恢复 Thread
-> 对话确认 Unknown 和 Conflict
-> 生成结构化 Project Model
-> Pydantic 验证
-> 生成能力需求
-> 本地解析
-> 展示 Recommendation 和 ChangeSet
-> 用户确认
-> 写入项目文件
-> Doctor 验证
```

### 初始化访谈

- 使用同一个 Codex Thread 完成访谈。
- 每轮用户输入形成一个 Turn。
- 监听 Agent Message、Reasoning、Command 和 Approval 事件。
- 保存 Thread ID，但不提交到项目 Git。
- 最终要求 Codex 输出 Project Model JSON。
- 使用 Pydantic 验证。
- 失败时在同一个 Thread 中进行最多两次修复。
- 仍然失败则保留原始输出并生成可诊断错误。

### 空白目录处理

- 检查目录是否为空。
- 在需要 Git 的 Codex 操作前请求用户确认 `git init`。
- 默认不跳过 Git 安全检查。
- 先生成 Blueprint 和项目 AI 配置，不擅自生成完整业务框架。

## 数据模型

所有核心配置使用 Pydantic Model 定义，并导出 JSON Schema。

模型要求：

- 使用显式 Schema Version。
- 默认禁止未知危险字段。
- 为向前兼容的外部协议保留未知字段。
- 将用户意图和解析结果分离。
- 将权限字段建模为枚举和作用域集合。
- 为每个模型提供迁移入口。

## 数据边界

### 项目文件

用户可编辑并可以进入 Git：

- Blueprint。
- Capabilities。
- Policies。
- Decisions。
- Workflows。
- Project Skill。

### 本地状态

不进入 Git：

- Codex Thread ID。
- Inventory 缓存。
- LangGraph Checkpoint。
- 执行 Run。
- 用户级信任决策。
- 本地绝对路径。
- 低敏感度使用统计。

默认保存到平台规范的用户状态目录，由 `platformdirs` 解析。

### 禁止保存

- Secret 值。
- 完整生产数据。
- 未经允许的完整对话记录。
- 第三方凭据。

## LLM 与确定性模块边界

### Codex 负责

- 理解项目目标。
- 识别含糊和冲突。
- 将用户语言转换成结构化意图。
- 提出能力需求候选。
- 解释推荐和权衡。
- 生成项目级 Skill 草案。

### Python 程序负责

- 读取仓库事实。
- Pydantic 和 JSON Schema 验证。
- 权限和策略检查。
- 兼容性过滤。
- 文件摘要。
- 版本和 Lockfile。
- ChangeSet。
- 文件写入和回滚。
- 命令存在性检查。
- Doctor。
- Capsule 失效。

## LangGraph 工作流

LangGraph 只用于控制面工作流，不接管 Codex 的编码执行能力。

### 初始化 Graph

```text
inspect
-> inventory
-> interview
-> model
-> resolve
-> review
-> apply
-> verify
-> complete
```

Interrupt：

- 等待用户回答。
- 等待推荐确认。
- 等待权限批准。
- 等待冲突解决。

### 任务 Graph

```text
classify
-> plan
-> execute_phase
-> verify_phase
-> replan | review
-> complete
```

### Checkpoint

- Checkpoint 使用 SQLite。
- Thread ID 和 Graph Run ID 分离。
- 每个节点输入输出使用 Pydantic Model。
- 恢复时重新验证仓库摘要和权限状态。
- 过时 Checkpoint 不直接继续执行。

## Context Capsule

Capsule 必须包含：

- Task ID。
- 意图。
- 范围。
- 约束。
- 验收标准。
- 当前阶段。
- 选中能力。
- 延后和拒绝能力。
- 引用来源和摘要。
- 失效条件。
- Token 预算。

Capsule 默认不包含：

- 全部 Skill 正文。
- 全部 MCP Schema。
- 完整项目历史。
- 无关文件内容。
- Secret。

## Capability Adapter

```python
class CapabilityAdapter(Protocol):
    kind: str

    async def discover(
        self,
        context: DiscoveryContext,
    ) -> list[DiscoveredCapability]: ...

    async def normalize(
        self,
        capability: DiscoveredCapability,
    ) -> CapabilityManifest: ...

    async def verify(
        self,
        manifest: CapabilityManifest,
    ) -> VerificationResult: ...
```

第一版 Adapter 只读，不安装和修改外部能力。

Hook Adapter 只读取 Hook 元数据、触发条件和声明权限，不执行 Hook，也不修改全局或项目级 Host 配置。Plugin 提供的 Hook 可以保留其 Plugin 来源关系，但应规范化为独立、可审计的能力组件。

## Practice Pack

Practice Pack 是版本化 YAML 数据，不是可执行代码。

```text
practice-packs/
├── base-engineering/
│   ├── pack.yaml
│   └── practices/
├── web-application/
├── backend-api/
└── security-sensitive/
```

使用 Pydantic 验证，每条 Practice 包含：

- 适用条件。
- 推荐强度。
- 抽象能力需求。
- 理由。
- 例外。
- 验证方法。

## 文件写入策略

### ChangeSet

```python
ChangeOperation = CreateOperation | UpdateOperation | DeleteOperation
```

第一版默认不生成 DeleteOperation。

### 原子写入

- 写入临时目录。
- 验证生成结果。
- 检查目标文件摘要未变化。
- 使用 `os.replace` 原子替换 Owned 文件。
- Managed 文件使用结构化 Patch。
- 失败时回滚。

## 持久化

### SQLAlchemy

用于：

- Inventory。
- Run。
- Thread。
- Capability Verification。
- Trust Decision。
- Audit Event。

LangGraph Checkpoint 使用官方 SQLite Checkpointer 管理的表结构，不由 SQLAlchemy 业务模型重复实现。业务持久化只保存 Graph Run ID、Codex Thread ID、Checkpoint Namespace 和当前输入摘要之间的关联，以便恢复前重新验证状态。

### Alembic

- 所有数据库变化使用 Migration。
- 启动时检查 Schema Version。
- 不在应用启动时隐式生成数据库结构。
- Migration 必须具有升级和降级测试。

## 错误处理

- 用户取消属于正常终止。
- 能力缺失输出 Gap，不伪装成功。
- Codex 结构化输出最多修复两次。
- `app-server` 崩溃时保存 Graph Checkpoint 并提供恢复。
- 仓库在确认后变化则重新生成 ChangeSet。
- Doctor 失败不删除用户文件。
- 未知项目类型回退到 `base-engineering`。

## 安全基线

- Inspect 默认只读。
- 第一版不运行第三方安装脚本。
- 第一版不自动联网搜索能力。
- 不读取 Secret 内容。
- 不修改全局 Codex 配置。
- 不使用 `danger-full-access`。
- 不使用 `curl | sh`。
- 写入前展示 Diff。
- 权限由确定性 Python 策略模块判断。
- `app-server` 子进程继承最小必要环境变量。
- 日志写入前执行敏感字段脱敏。

## 测试策略

### Unit

- Pydantic Model。
- Repository Scanner。
- Capability Adapter。
- Practice Matcher。
- Resolver。
- Context Compiler。
- Permission Policy。

### Property-Based

使用 Hypothesis 验证：

- 任意合法 Blueprint 可以序列化和恢复。
- ChangeSet 重复应用不会静默覆盖变化。
- Capsule 失效条件不会漏掉关键来源变化。
- 权限合并不会产生隐式扩大。

### Integration

- Fake app-server JSON-RPC Process。
- 实际 Codex app-server 协议 Smoke Test。
- SQLite 和 Alembic Migration。
- Skill 和 MCP Inventory。

### E2E

- 空白项目。
- 已有项目。
- 多 Skill 环境。
- 无 Skill 环境。
- 用户取消和恢复。
- 高风险审批。

## 可观测性

第一版记录本地事件：

- 命令开始和结束。
- LangGraph 节点。
- Codex Thread 和 Turn ID。
- 事件耗时和 Token 使用量。
- 选中和拒绝能力 ID。
- ChangeSet 摘要。
- Doctor 结果。

不记录完整代码、Secret 或完整对话。

## 架构演进接口

第一版保留但不立即实现：

- RemoteCatalogAdapter。
- InstallerAdapter。
- HostAdapter。
- PolicyEngineAdapter。
- TelemetryExporter。
- TemplateAdapter。
