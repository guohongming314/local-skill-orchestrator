# 相似设计与开源复用分析

**日期：** 2026-07-13  
**状态：** 调研完成  
**目标：** 找出可直接复用的开源项目、可借鉴的架构模式，以及当前设计仍需调整的地方

## 结论

当前产品方向是合理的，但不应该从零实现一个完整 Agent Framework。

最合理的实现策略是：

```text
复用 Agent Skills 标准和现有安装工具
+ 复用 MCP 官方 SDK 和渐进发现模式
+ 复用成熟状态机管理任务生命周期
+ 复用本地搜索和结构化配置基础设施
+ 复用模板、迁移、安全和可观测性工具
+ 只自研项目建模、能力本体、推荐品味和上下文编译逻辑
```

产品真正需要自研的部分只有：

1. 项目事实和目标模型。
2. 抽象能力本体。
3. Practice Packs。
4. 意图、风险和任务场景分类。
5. 本地能力解析和外部候选评分。
6. Context Capsule 编译策略。
7. 面向编码 Agent 的项目级配置生成。

其余能力应优先通过开源库或标准完成。

## 最接近当前设计的项目和模式

### 1. MCP Progressive Discovery

MCP 官方客户端最佳实践已经提出两种与当前设计高度一致的模式：

- Progressive Discovery：只在需要时让工具定义进入上下文。
- Programmatic Tool Calling：将工具调用控制从模型上下文中进一步分离。

这直接支持“完整能力目录保存在控制面，执行面只看到当前阶段的少量工具”。

应直接采用的设计：

```text
轻量工具目录
-> 根据任务检索候选
-> 只公开 Top-K 工具
-> 允许 none-of-the-above
-> 执行中按阶段继续发现
```

参考：<https://modelcontextprotocol.io/docs/develop/clients/client-best-practices>

### 2. Pydantic AI Toolsets 和 Capabilities

Pydantic AI 的 Toolset 支持：

- 动态决定一次运行可用的工具集合。
- 组合和过滤工具定义。
- 包装审批策略。
- 将本地工具和 MCP 统一为 Toolset。

其 Capabilities 抽象可以将工具、Hooks、指令、模型设置和历史处理组合为一个能力。

这与本项目的“抽象能力 -> 具体提供者 -> 使用策略”非常接近。

可借鉴：

- `Capability` 作为一级扩展单位。
- Toolset 动态过滤。
- ApprovalRequiredToolset。
- 运行上下文参与能力选择。

不建议第一版直接采用 Pydantic AI 作为核心运行时。虽然产品已经选择 Python，但实际编码执行者仍然是 Codex，控制面只需要复用其 Capability、Toolset 和审批思想，不需要再建立第二套 Agent Runtime。

参考：

- <https://pydantic.dev/docs/ai/tools-toolsets/toolsets/>
- <https://pydantic.dev/docs/ai/core-concepts/capabilities/>

### 3. XState

XState 提供状态机、Statecharts、Actor Model、持久化、恢复和可视化能力。

它适合实现：

- `init` 生命周期。
- Fast、Standard、Rigorous 任务工作流。
- 阶段切换和动态重规划。
- 审批等待。
- 失败恢复。
- 可序列化任务状态。
- 工作流测试。

XState 仍然是值得参考的状态建模项目，但 Python 主架构不直接依赖 XState。它的 Statecharts、Actor 和持久化设计用于校验我们的工作流模型是否完整。

示例状态：

```text
inspect
-> clarify
-> resolve-capabilities
-> review-plan
-> apply
-> verify
-> completed
```

任务运行状态：

```text
classify
-> investigate
-> design
-> implement
-> verify
-> review
-> completed
```

参考：

- <https://github.com/statelyai/xstate>
- <https://stately.ai/docs/persistence>

### 4. LangGraph

LangGraph 的 Checkpointer、Interrupt 和 Human-in-the-loop 模型适合长时间运行、需要暂停批准和故障恢复的 Agent 工作流。

Python 主架构直接使用 LangGraph 作为控制面工作流引擎，不再同时引入 XState。

选择规则：

```text
Python 本地 CLI            -> LangGraph
Codex 交互                 -> codex app-server JSON-RPC
能力模型和验证             -> Pydantic
主要依赖 Codex 执行任务    -> 不自建完整 Agent Runtime
```

参考：<https://docs.langchain.com/oss/python/langgraph/persistence>

### 5. OpenHands Skills

OpenHands 已经采用：

- `AGENTS.md` 保存长期规则。
- 项目 Skills 优先于用户级 Skills。
- 先显示 Skill 摘要，再按需加载完整内容。
- 官方扩展仓库和社区技能安装。
- Hooks 执行确定性检查。

这证明当前设计的“项目级薄 Skill + 按需加载 + 仓库优先级”与主流方向一致。

可以借鉴：

- 项目级覆盖顺序。
- Skill Registry Adapter。
- `/add-skill` 式安装体验。
- Hooks 和 Skill 的职责区分。

参考：

- <https://docs.openhands.dev/overview/skills>
- <https://docs.openhands.dev/openhands/usage/customization/repository>

### 6. Continue 配置模型

Continue 使用声明式配置组合：

- Models。
- Rules。
- Prompts。
- Docs。
- MCP Servers。
- Tools。

它证明了能力环境需要一个结构化配置源，而不是只靠 Prompt。

可以借鉴：

- 多配置源和优先级。
- YAML 配置结构。
- Rules、Tools 和 MCP 分离。
- 用户级和项目级配置合并。

参考：<https://docs.continue.dev/reference>

### 7. Goose Recipes 和 Extensions

Goose 是一个开源 Agent，提供 CLI、桌面端、API、Recipes 和大量 MCP Extensions。

可以借鉴：

- Recipe 表达可重复执行的工作流。
- Extension 目录和启用状态。
- MCP 能力适配层。
- CLI、桌面和 API 共用能力模型。

当前产品不需要复用 Goose 运行时，但可以为 Goose Recipe 和 Extension 增加导入 Adapter。

参考：<https://block.github.io/goose/>

### 8. GitHub Agentic Workflows

GitHub Agentic Workflows 采用：

```text
自然语言 Markdown 工作流
-> 编译
-> 生成锁定后的 GitHub Actions Workflow
-> 在沙箱和权限策略下运行
```

这个模式与当前产品的 Context Compiler 非常接近。

最值得借鉴的是：

- 人类可读的源配置和机器锁定产物分离。
- 编译期验证。
- Action 固定版本。
- 安全输出门禁。
- 网络白名单。
- 成本和追踪。

当前项目也应该采用：

```text
Blueprint / Workflows / Policies
-> 编译
-> Context Capsule / Resolution Plan / Lockfile
```

参考：<https://github.github.com/gh-aw/>

### 9. Nx、Copier、Backstage 和 Dev Containers

这些项目不直接解决 Agent 上下文，但提供成熟的项目装配模式。

#### Nx

可借鉴或复用：

- 虚拟文件树。
- Generator。
- Dry-run。
- Migration。
- Sync Check。

对 JavaScript/TypeScript 工作区可以直接编写 Nx Adapter，而不是重写项目图和生成器体系。

#### Copier

可直接作为项目模板 Adapter：

- 保存 answers 文件。
- 模板更新。
- 三方合并。
- 版本迁移。

不需要自研完整的可升级模板系统。

#### Backstage

借鉴：

- Catalog。
- Template Parameters。
- Actions。
- Dry-run。
- 审计和授权。

不建议直接依赖完整 Backstage，因为对于本地个人和小团队场景过重。

#### Dev Containers

直接采用其 Template 和 Feature 思路：

```text
Project Template = 项目整体起点
Capability Feature = 可组合单项能力
```

参考：

- <https://nx.dev/docs/reference/devkit>
- <https://copier.readthedocs.io/en/stable/configuring/>
- <https://backstage.io/docs/next/software-templates/generated-index/>
- <https://github.com/devcontainers/spec>

## 推荐直接复用的开源组件

### 必须复用

| 领域 | 推荐项目 | 用途 |
|---|---|---|
| Skill 标准 | Agent Skills Specification | 解析和生成标准 Skill |
| Skill 安装 | `skills` CLI | 搜索、安装和跨 Agent 分发 |
| MCP | 官方 Python SDK | MCP 客户端、服务端和元数据读取 |
| 工作流 | LangGraph | 状态图、审批、中断、恢复和 Checkpoint |
| Schema | Pydantic v2 + jsonschema | Blueprint、Manifest 和 Capsule 验证 |
| YAML | `ruamel.yaml` | 可保留注释的 YAML 读写 |
| 本地状态 | SQLite + SQLAlchemy/Alembic | Inventory、Lock、Run、迁移和审计数据 |
| 可观测性 | OpenTelemetry | 初始化和任务编排 Trace |

来源：

- <https://github.com/agentskills/agentskills>
- <https://github.com/vercel-labs/skills>
- <https://github.com/modelcontextprotocol/python-sdk>
- <https://docs.langchain.com/oss/python/langgraph/persistence>
- <https://github.com/openai/codex/tree/main/codex-rs/app-server>
- <https://opentelemetry.io/>

### 建议复用

| 领域 | 推荐项目 | 使用建议 |
|---|---|---|
| CLI 框架 | Typer | 命令解析和 Python 类型集成 |
| 终端呈现 | Rich + prompt_toolkit | 流式事件、审批和交互问答 |
| 异步运行时 | AnyIO | 管理 app-server 子进程和并发事件 |
| 本地文本检索 | SQLite FTS5 | MVP 的 Skill、能力和文档检索 |
| 混合检索 | 后期评估 Python 检索库 | 只有评测证明需要时引入 |
| 向量检索 | 后期 Adapter | 不作为第一版关键依赖 |
| 模板更新 | Copier | 可升级项目模板和迁移 |
| JS 工作区 | Nx DevKit | 项目图、生成器和迁移 Adapter |
| 策略引擎 | OPA | 组织级复杂策略阶段使用 |
| 授权策略 | Cedar | 需要细粒度授权时评估 |

### 不建议第一版引入

- 同时引入 LangGraph、Pydantic AI 和另一套主工作流引擎。
- 自建向量数据库服务。
- 自建完整 Agent Runtime。
- 自建 Skill 包管理器。
- 自建 MCP 协议实现。
- 直接依赖完整 Backstage。
- 默认部署远程控制服务。
- 为少量工具引入复杂语义检索系统。

## 推荐内部数据结构

### `capability.manifest.yaml`

需要增加统一能力 Manifest，将 Skill、Tool、MCP 和 Plugin 归一化：

```yaml
schema_version: 1
id: code-graph-analysis
provider: local-codegraph
kind: plugin

provides:
  - code-graph-analysis
  - symbol-impact-analysis

compatibility:
  agents: [codex]
  platforms: [darwin, linux]

permissions:
  - repo.read
  - repo.execute

use_when:
  - repository.size == large
  - task.scope == cross-module

avoid_when:
  - task.scope == single-file

verification:
  command: codegraph doctor

fallbacks:
  - language-server
  - text-search
```

第三方能力没有此文件时，由 Adapter 生成规范化 Manifest。

### `resolution-plan.yaml`

在写入项目配置前保存一次可审查解析结果：

```yaml
requirements:
  - browser-verification

selected:
  browser-verification:
    provider: playwright
    source: project-tool
    reason: 项目已有 Node 运行时且无需外部凭据

rejected:
  browser-mcp:
    reason: 当前任务不需要交互式外部浏览器控制
```

### `context-capsule.yaml`

需要增加来源、有效期和内容摘要：

```yaml
schema_version: 1
task_id: task-123
phase: investigate
created_at: 2026-07-13T12:00:00Z
expires_when:
  - git_head_changes
  - user_scope_changes
  - phase_changes

sources:
  - path: AGENTS.md
    digest: sha256:...
  - capability: systematic-debugging
    version: 1.2.0
```

避免 Agent 使用已经过时的 Capsule。

### `execution-run.jsonl`

使用追加日志记录：

- 意图解析。
- 用户确认。
- 能力选择。
- 工具调用摘要。
- 阶段变化。
- 验证结果。
- 失败和重新编译原因。

默认不记录 Secret、完整文件内容或完整对话。

## 当前设计遗漏和调整建议

### 1. 项目级 Skill 无法单独实现真正的动态工具暴露

这是目前最重要的技术缺口。

项目级 Skill 可以告诉模型“不要使用某些工具”，但如果 Agent Host 已经把全部 MCP Tool Schema 放进上下文，Skill 无法真正移除这些 Schema。

因此需要区分两种能力：

```text
软路由
通过项目 Skill 指导 Codex 选择能力。

硬路由
通过 CLI Launcher、Plugin、MCP Gateway 或 Host SDK，
只向当前会话暴露选中的工具和服务器。
```

MVP 可以先实现软路由。真正的上下文节省需要后续增加 Host Adapter。

### 2. 需要工具检索评测，而不只是语义相似度

研究表明，大规模工具选择是一个 Retrieval + Planning 问题。单次向量相似度可能遗漏多步骤任务需要的工具，也可能受到描述相近工具干扰。

建议采用：

```text
能力分类
-> 召回候选
-> 按当前阶段过滤
-> LLM 在小集合中选择
-> none-of-the-above
-> 需要时再次检索
```

第一版使用 SQLite FTS5 足够。只有候选规模和评测证明有必要时才引入向量检索。

### 3. Context Capsule 需要失效机制

当前设计有动态重编译，但缺少精确失效条件。

至少在以下变化后失效：

- Git HEAD 或工作区关键文件变化。
- 用户目标、范围或约束变化。
- 项目配置变化。
- 能力版本或可用状态变化。
- 工作流阶段变化。
- 权限策略变化。

### 4. LLM 决策和确定性决策必须分离

LLM 适合：

- 理解意图。
- 识别含糊点。
- 生成候选能力需求。
- 解释推荐理由。

确定性代码负责：

- Schema 验证。
- 权限判定。
- 兼容性过滤。
- 版本锁定。
- 文件 Diff。
- 命令执行。
- 验证结果。
- 安装事务和回滚。

不得让模型直接绕过策略引擎执行高风险操作。

### 5. 需要持久化运行状态和恢复

初始化、安装、审批和复杂任务可能跨越多个进程和会话。应使用 LangGraph Checkpoint 和事件日志保存状态，而不是依赖聊天历史恢复。

### 6. 需要意图和路由评测集

没有评测集就无法知道 Context Compiler 是否真的比普通 Skill 路由更好。

至少建立：

- 50 个简单任务。
- 50 个普通开发任务。
- 50 个高风险任务。
- 任务意图、风险、应选工作流和应选能力的人工标注。
- 不应调用任何额外能力的负样本。
- 工具描述冲突和近似名称样本。
- 用户中途改变目标的重编译样本。

评测指标：

- 意图分类准确率。
- 能力 Recall@K。
- 无关能力选择率。
- Capsule Token 数。
- 任务完成率。
- 用户覆盖率。
- 错误权限请求率。

### 7. 需要明确支持范围

跨 Codex、Claude Code、Gemini、Copilot 和 Cursor 的统一适配具有很高复杂度。

第一版应该明确：

```text
第一目标：Codex
第二目标：通用 Agent Skills 兼容
后续：Claude Code、Copilot、Gemini 和其他 Host Adapter
```

### 8. 不应自动从历史结果学习并修改策略

任务结果可以生成建议，但不能静默改变项目规则。

正确流程：

```text
发现重复模式
-> 生成策略调整建议
-> 用户确认
-> 写入 Blueprint 或 Practice Pack Override
```

### 9. 需要成本和延迟预算

每次编译应该限制：

- 最大检索候选数。
- 最大 Capsule Token 数。
- 最大 LLM 分类次数。
- 最大工具发现轮次。
- 最大外部网络请求。

否则“节省执行上下文”可能被控制面过高成本抵消。

### 10. 需要隐私等级

所有输入和能力应标记：

```text
public
project
private
secret
production-sensitive
```

Context Compiler 只能将符合当前执行环境策略的数据放入 Capsule。

## 推荐技术路线

### 第一版

```text
Python 3.12+
+ uv
+ Typer
+ Rich / prompt_toolkit
+ AnyIO
+ Pydantic / jsonschema
+ ruamel.yaml
+ SQLite / SQLAlchemy / Alembic
+ SQLite FTS5
+ LangGraph
+ Agent Skills Specification
+ skills CLI Adapter
+ MCP Python SDK
+ codex app-server JSON-RPC
```

第一版仍由 Codex 执行任务，不自建模型调用循环。Python 通过 `codex app-server` 管理 Thread、Turn、事件和审批。

### 第二版

- Host Adapter 和硬工具路由。
- MCP Progressive Discovery。
- 根据评测选择 Python 混合检索实现。
- Copier 和 Nx Adapter。
- OpenTelemetry Trace。
- OSV 和 OpenSSF 安全信号。
- 可视化计划和审批界面。

### 第三版

- 组织能力目录。
- OPA 或 Cedar 策略集成。
- 多 Agent Host Adapter。
- 远程团队配置同步。
- 基于评测和真实结果的推荐校准。

## 最终判断

当前产品不需要重新发明 Agent Framework、Skill 规范、MCP、工作流状态机、模板迁移、搜索引擎或策略引擎。

产品应该成为这些开源能力之上的一层：

> 将项目事实和用户意图编译成最小、可信、可执行上下文的控制面。

最重要的差异化不是“我们支持多少工具”，而是：

- 是否理解当前项目真正需要什么。
- 是否知道什么时候不应推荐能力。
- 是否能把能力绑定到正确工作流阶段。
- 是否能够控制上下文、权限和成本。
- 是否能通过评测证明推荐比直接暴露全部能力更好。
