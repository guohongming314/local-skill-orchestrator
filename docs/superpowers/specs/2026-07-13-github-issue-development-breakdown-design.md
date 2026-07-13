# GitHub Issue 级开发计划拆分设计

**日期：** 2026-07-13  
**状态：** 待用户复核  
**上游设计：** `2026-07-13-project-ai-capability-bootstrapper-design.md`  
**上游计划：** `docs/plans/2026-07-13-mvp-implementation-plan.md`

## 目标

将当前 16 个高层实施 Step 转换为可直接创建 GitHub Issue、可独立开发、可独立测试和可独立合并的工作项，同时保留从产品目标到验收结果的可追溯性。

## 拆分策略

采用“Epic + 纵向可交付 Issue”结构：

- Epic 表示一个稳定的产品或工程能力边界。
- Issue 优先交付可观察行为，而不是只交付某个技术层。
- 公共基础组件可以单独成为 Issue，但必须有明确消费方、测试和后续解锁能力。
- 单个 Issue 的预期工作量为 0.5–2 人日。超过 2 人日或同时跨越多个子系统时必须继续拆分。
- 对协议、运行时和第三方集成中无法可靠估算的工作，先创建有明确退出条件的限时 Spike，再根据 Spike 结论创建实现 Issue；不为了满足人日范围伪造精确估算。
- 每个 Issue 使用 TDD 顺序：失败测试、最小实现、通过测试、质量检查。
- 测试资产随能力同步交付。Epic 10 负责跨模块验收和发布门禁，不负责到项目末期才开始补建 Fixture、Doctor 检查或评测数据。

## Epic 边界

### Epic 0：工程与质量底座

建立可持续开发所需的 CLI 骨架、依赖、测试、静态检查和基础 CI。该 Epic 不实现业务能力。

### Epic 1：核心领域模型与持久化

定义 Repository Snapshot、Blueprint、Capability Manifest、Resolution Plan、Task、Risk 和 Context Capsule 等稳定契约，并建立 Run、Codex Thread、Inventory Cache、Capability Verification、用户信任决策和 Audit Event 的本地持久化。该 Epic 同时定义 Graph Run、Codex Thread 和 LangGraph Checkpoint 的身份与关联契约；Checkpoint 的运行集成在 E2 验证。

### Epic 2：Codex app-server 技术验证

验证 JSON-RPC 生命周期、多轮 Turn、审批请求、Thread 恢复、结构化输出和 `codex exec` 回退路径，并完成最小 LangGraph 初始化 Graph 与 SQLite Checkpoint Spike。该 Spike 必须证明 Codex Thread ID 与 Graph Run ID 分离、进程中断后可以恢复、恢复前会重新验证输入摘要。Epic 结果必须形成可重用适配层、Fake app-server 测试设施和 ADR，不只是一次性脚本。

### Epic 3：`vibe inspect` 仓库分析

通过确定性规则生成可重复的仓库事实快照，覆盖 Git、语言、框架、包管理器、工程命令、CI、容器、数据库、Agent 指令和 Monorepo。

### Epic 4：`vibe capabilities` 本地能力盘点

扫描 Agent Skills、CLI Tools、Codex MCP、Plugins 和 Hooks 元数据，将它们规范化为 Capability Manifest，并提供列表、解释和只读健康检查。Hook 在当前范围内只做元数据发现、权限描述和风险标注，不执行 Hook，也不修改 Host 配置。

### Epic 5：`vibe init --model-only` 项目建模

基于 E2 已验证的 LangGraph 和 Checkpoint 基础设施，组合 Inspect、Inventory 与 Codex 访谈，让用户确认项目目标、阶段、风险、约束、偏好和锁定决策，最终生成可审阅的 Blueprint。E5 不重新承担工作流运行时 Spike。

### Epic 6：Practice Pack 与本地能力解析

将 Blueprint 转换为抽象能力需求，通过硬过滤、策略和可解释评分优先绑定本地能力，输出选中、拒绝、延后和 Gap 理由。首批必须覆盖 `base-engineering`、`web-application`、`backend-api`、`cli-tool`、`open-source-library`、`database-backed`、`security-sensitive` 和 `ai-application` 八个 Practice Pack；允许按共享 Schema 和匹配引擎先后分批交付。

### Epic 7：Dry-run 与项目配置生成

生成 ChangeSet，安全写入 `AGENTS.md`、`.ai-project/`、项目级 Skill 和 Capability Lockfile。实现 Owned、Managed 和 Observed 所有权模型、并发变更检测与失败回滚。

### Epic 8：`vibe doctor` 和漂移检测

提供统一 Doctor 检查框架、严重级别、报告格式和最终聚合命令，检查 Schema、能力引用、命令存在性、文件摘要、权限、技术栈、生成文件和 Capsule 失效条件，并输出可执行的修复建议。各领域检查随对应 Epic 左移交付：Schema 随 E1、Codex 运行状况随 E2、仓库事实随 E3、Inventory 随 E4、生成文件随 E7、Capsule 失效随 E9；E8 负责公共框架、跨领域组合和 `vibe doctor`/`vibe diff` 验收。

### Epic 9：任务规划与 Context Capsule

评估风险、选择工作流、绑定阶段能力，通过 `vibe plan` 生成最小且可失效的 Context Capsule。任务场景分层交付：

- P0 完整纵向场景：Bug、Feature、Refactor、Security、Migration 和 Review，必须具有专用分类、风险策略、工作流、Fixture 和验收。
- P1 Registry 场景：Performance、Dependency Upgrade、Testing、UI/Accessibility、Documentation、Release、Incident 和 Exploration，必须具有注册定义、风险策略、Fixture、可解释路由和安全降级；只有评测证明需要时才增加专用工作流。

### Epic 10：端到端验收与发布准备

聚合各 Epic 已持续建设的 Fixture 和测试资产，完成跨模块端到端测试、Bootstrap Skill、项目 Skill 校验、离线任务路由评测和发布门禁，证明核心用户链路在空白项目、小型项目、Monorepo 和限制环境中可用。任务评测集至少包含 30 个简单任务、30 个普通任务、30 个高风险任务，以及各 20 个零额外能力、用户中途改目标、能力名称或描述冲突样本；报告意图准确率、风险准确率、Capability Recall@K、无关能力选择率、Capsule 大小、错误权限请求率、端到端配置成功率和 Doctor 漂移检测率。首个基线 Issue 负责记录现状，后续发布门禁 Issue 根据基线设定并固化阈值。

## Issue 模板

每个 Issue 必须包含以下内容：

1. **标题**：使用可验收的动词短语，例如“实现 Node 包管理器检测与冲突报告”。
2. **用户价值**：说明完成后解锁的用户行为或工程能力。
3. **范围**：列出必须实现的具体行为。
4. **非目标**：列出本 Issue 明确不解决的相邻问题。
5. **依赖**：使用 Epic/Issue 编号表示前置条件；无依赖时明确写“无”。
6. **文件范围**：列出预期创建、修改和测试的精确路径。
7. **契约影响**：声明是否修改公共 Schema、CLI 输出、数据库 Migration、生成文件格式或跨 Epic Interface；无影响时明确写“无”。
8. **实施步骤**：按失败测试、最小实现、通过测试和质量检查拆分。
9. **验收标准**：使用可观察的 Given/When/Then 或等价断言。
10. **验证命令**：列出精确命令和预期结果。
11. **元数据**：建议 Epic、标签、优先级、工作量、是否为 Spike 和是否可并行。

## 编号和依赖规则

- Epic 使用 `E0`–`E10`。
- Issue 使用 `<Epic>.<序号>`，例如 `E3.4`。
- 依赖只指向必须先完成的 Issue，不把“可以参考”写成阻塞依赖。
- 可并行 Issue 必须避免同时修改同一高冲突文件；无法避免时在元数据中标记为不可并行。
- 跨 Epic 依赖只保留必要的稳定契约，避免所有工作串行化。
- 修改公共 Schema、Migration、CLI 输出或生成文件格式的 Issue 默认不是 `parallel-safe`；只有契约变更先独立合并或兼容层已经落地时才能并行。
- E8 和 E10 不是所有领域工作的统一尾部依赖。领域 Doctor、Fixture 和评测样本应由对应功能 Issue 创建，E8/E10 只依赖需要聚合的稳定输出。

## 标签与优先级

建议标签：

- 类型：`type:feature`、`type:infra`、`type:test`、`type:docs`。
- 领域：`area:models`、`area:codex`、`area:inspect`、`area:inventory`、`area:init`、`area:resolver`、`area:materialize`、`area:doctor`、`area:compiler`。
- 优先级：`priority:P0`、`priority:P1`、`priority:P2`。
- 规模：`size:S` 约 0.5 人日、`size:M` 约 1 人日、`size:L` 约 2 人日。
- 状态补充：`blocked`、`parallel-safe`、`needs-adr`、`integration-test`。

P0 表示当前端到端主路径必须的能力；P1 表示进入对应 Epic 验收前必须完成；P2 表示不阻塞当前交付的增强项。

## 验收与完成定义

单个 Issue 只有在以下条件全部满足时才算完成：

- Issue 中声明的行为已实现，非目标未被意外扩展。
- 新增或修改行为有自动化测试。
- 指定的 `pytest`、`ruff` 和 `mypy` 命令通过。
- 用户可观察输出与 Schema 兼容，且错误信息可操作。
- 不读取 Secret 内容，不扩大已声明权限。
- 相关文档、Fixture 和 ADR 已同步。
- 如果修改公共契约，已经提供兼容策略、Migration 或明确的版本升级行为。

Epic 完成时还必须运行该 Epic 的 CLI 或端到端验收命令，不以“所有子 Issue 已关闭”替代产品行为验收。

## 计划文档输出

用户批准本设计后，实施计划将保存到：

`docs/superpowers/plans/2026-07-13-github-issue-development-plan.md`

该文档将：

- 列出 E0–E10 下的完整 Issue。
- 提供可直接复制到 GitHub 的标题和正文。
- 标明前置依赖、关键路径和并行开发批次。
- 将原 16 个 Step 和产品路线图的验收要求映射到具体 Issue。
- 提供单独的追溯矩阵，逐项覆盖产品路线图完成标准、MVP 范围、量化评测指标和发布条件，不只在 Epic 层面标记“已覆盖”。

## 边界

本计划只覆盖当前已批准的 Codex 本地优先产品范围。远程能力发现、自动安装、硬工具路由、多 Host 适配和持续治理不进入 Issue 清单。
