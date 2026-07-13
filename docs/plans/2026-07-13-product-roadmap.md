# AI 项目能力初始化器产品路线图

**日期：** 2026-07-13  
**状态：** 可进入开发  
**临时命令名：** `vibe`  
**首要目标平台：** Codex

## 产品目标

将用户意图、项目事实、当前可用能力和工程实践动态编译为：

1. 项目级能力配置。
2. 项目级开发规则和工作流。
3. 当前任务所需的最小 Context Capsule。
4. 可解释、可验证、可调整的执行计划。

产品分成两个闭环：

```text
项目初始化闭环
分析仓库 -> 确认目标 -> 盘点能力 -> 解析缺口
-> 用户确认 -> 生成配置 -> 验证

任务执行闭环
解析意图 -> 判断风险 -> 选择工作流 -> 绑定能力
-> 编译上下文 -> 执行 -> 验证 -> 记录结果
```

## 已确认的产品决策

- 第一版只针对 Codex 深度集成。
- 使用 Python 3.12+ 和 Codex `app-server` JSON-RPC。
- 第一版由 Codex 执行任务，不自建 Agent Runtime。
- 第一版只使用本地能力，不自动安装远程能力。
- 项目级 Skill 实现软路由。
- 后续 Host Adapter 实现硬工具路由。
- 使用 LangGraph 管理初始化和任务工作流。
- 使用 YAML 保存用户可编辑配置。
- 使用 SQLite 保存本地 Inventory、Run 和审计状态。
- 使用 Agent Skills 标准，不自建 Skill 格式。
- 使用 MCP 官方 SDK，不自建 MCP 协议。
- 默认能力是工程能力，不是具体产品全家桶。
- CodeGraph、Claude-Mem 等属于条件能力。
- LLM 负责理解和解释，确定性代码负责权限、版本、写入和验证。

## 目标总览

| 目标 | 范围 | 可交付结果 |
|---|---|---|
| 建立可靠控制面 | 工程基础、Codex 集成、确定性仓库分析、本地能力盘点 | 可运行 CLI、稳定事实快照、Capability Inventory、Schema、持久化和 ADR |
| 完成项目初始化闭环 | 对话式项目建模、Practice Packs、本地能力解析、安全生成和 Doctor | `vibe init` 从项目目标生成可审阅、可复现、可验证的项目配置 |
| 完成任务编排并达到发布标准 | 意图与风险判断、工作流、Context Capsule、场景评测和发布门禁 | `vibe plan` 为真实任务生成最小执行上下文，核心场景通过安全与质量验证 |

可信远程发现、安全安装、硬路由、持续治理和多平台适配是后续能力方向。它们只有在当前三个目标完成且有明确需求时才进入开发计划，不按“第二版”预先承诺。

## 目标一：建立可靠控制面

### 目标状态

证明核心技术路径可以工作，避免正式开发后才发现 Codex 集成、交互或结构化输出不可行。

### 需要完成

- 初始化 Python CLI 工程。
- 确定 Python 最低版本和 uv 工程配置。
- 接入 Codex `app-server` JSON-RPC。
- 使用 `app-server` 启动线程并进行两轮对话。
- 验证线程 ID 可以持久化和恢复。
- 验证最终结构化项目模型的获取方式。
- 验证 `codex exec --output-schema` 作为结构化输出回退方案。
- 使用 Pydantic 创建 Blueprint、Capability Manifest、Resolution Plan 和 Context Capsule Schema。
- 创建最小 SQLite 数据库。
- 创建 LangGraph 初始化 Graph Spike。
- 验证 SQLAlchemy 和 Alembic 迁移。
- 写入安全和隐私 ADR。

### 完成标准

```text
vibe spike-codex
```

可以：

1. 分析当前目录的少量元数据。
2. 启动 Codex 对话。
3. 处理 Codex 事件和审批请求。
4. 接收用户回答。
5. 输出通过 Pydantic 验证的 JSON。
6. 保存 Thread、Turn 和 Graph Run 记录。

### 不包含

- 能力发现。
- 项目文件生成。
- 远程搜索。
- 实际安装。

### 仓库事实分析

### 目标状态

`vibe inspect` 不依赖模型也能生成可靠、可重复的仓库事实快照。

### 能力范围

- 判断空白目录或已有仓库。
- 查找 Git 根目录和状态。
- 识别语言和框架。
- 识别包管理器。
- 识别构建、启动、测试、Lint、Format 和 Typecheck 命令。
- 识别 CI、容器、数据库、迁移和部署配置。
- 识别 `AGENTS.md`、`CLAUDE.md`、`GEMINI.md` 和 Cursor Rules。
- 识别 Monorepo 和工作区。
- 输出 Confirmed、Inferred、Unknown 和 Conflict。
- 保存文件摘要，用于后续失效检测。

### 完成标准

```bash
vibe inspect
vibe inspect --json
```

在测试仓库中重复执行产生相同结果；无法确认的信息不会被伪装成事实。

### 本地能力盘点

### 目标状态

系统可以回答“本机和当前项目已经拥有什么能力”。

### 能力范围

- 扫描 Agent Skills。
- 解析 `SKILL.md` 元数据。
- 识别项目级和用户级作用域。
- 检查 Skill 依赖的工具和运行时。
- 检测常用 CLI Tools。
- 读取 Codex MCP 配置和连接状态。
- 读取已安装 Plugins 和 Hooks 元数据。
- 支持 Capability Adapter。
- 将复合产品规范化为 Capability Manifest。
- 计算内容摘要和版本身份。
- 不读取 Secret 内容。

### 首批 Adapter

- Agent Skill。
- CLI Tool。
- Codex MCP。
- Codex Plugin。
- CodeGraph 类本地代码分析工具。
- Claude-Mem 类本地记忆工具。

### 完成标准

```bash
vibe capabilities list
vibe capabilities explain <id>
vibe capabilities doctor
```

每项能力都有来源、作用域、提供能力、权限、兼容性和验证状态。

## 目标二：完成项目初始化闭环

### 对话式项目建模

### 目标状态

用户执行 `vibe init` 后，系统基于仓库事实只询问必要问题，并生成用户可编辑的 Blueprint。

### 运行入口

```text
CLI 确定性扫描
-> Codex app-server 启动初始化线程
-> 将事实快照和待确认项提供给 Codex
-> 多轮对话
-> 结构化 Project Model
-> Schema 验证
-> 用户最终确认
```

### 对话要求

- 不询问可以从仓库确认的问题。
- 不要求用户理解具体 Skill、MCP 或 Plugin。
- 询问目标、阶段、风险、约束和偏好。
- 清楚区分系统推断和用户确认。
- 支持返回修改之前的答案。
- 支持锁定决定。
- 支持推荐默认值和查看理由。

### 空白项目

- 先确认项目目标。
- 经用户同意后初始化 Git。
- 不直接创建完整业务项目。
- 生成项目 Blueprint 和建议能力需求。

### 完成标准

`vibe init --model-only` 可以生成通过 Schema 验证的 `blueprint.yaml`，且用户可以在写入前审阅和修改。

### Practice Packs 和本地能力解析

### 目标状态

系统将项目模型转换成抽象能力需求，并优先绑定本地能力。

### 首批 Practice Packs

- `base-engineering`
- `web-application`
- `backend-api`
- `cli-tool`
- `open-source-library`
- `database-backed`
- `security-sensitive`
- `ai-application`

### 首批能力需求

- 仓库探索。
- Git 和恢复。
- 构建和验证。
- 测试。
- 代码关系分析。
- 项目连续性记忆。
- UI 和可访问性。
- 数据库迁移。
- 安全审查。
- 浏览器验证。
- 发布和回滚。

### 解析规则

- 先硬过滤，再评分。
- 允许零个额外能力。
- 本地存在不等于必须选择。
- 记录选中、拒绝和延后理由。
- 为缺失能力生成 Gap，不搜索网络。
- 生成 `resolution-plan.yaml`。

### 完成标准

给定相同 Blueprint 和 Inventory，解析结果稳定、可解释、可测试。

### 项目配置生成和治理

### 目标状态

系统可以安全地将确认结果写入项目，并在后续检查漂移。

### 生成内容

```text
AGENTS.md
.ai-project/
├── blueprint.yaml
├── capabilities.yaml
├── capabilities.lock
├── policy.yaml
├── decisions.md
├── quality-gates.md
├── workflows.yaml
├── task-policies.yaml
└── capability-usage.yaml
.agents/skills/project-development/
├── SKILL.md
└── references/
```

### 文件安全

- 支持 Owned、Managed 和 Observed。
- 默认不覆盖已有 `AGENTS.md`。
- 使用结构化修改或标记区块。
- 所有写入先生成 ChangeSet。
- 支持 `--dry-run`。
- 写入失败时回滚。
- 保存内容摘要和生成版本。

### Doctor

检查：

- 配置 Schema。
- 引用能力是否存在。
- 命令是否存在。
- 项目事实是否漂移。
- Lockfile 是否失效。
- 权限是否扩大。
- 生成文件是否被人工修改。

### 完成标准

```bash
vibe init --dry-run
vibe init
vibe doctor
vibe diff
```

在空白项目和已有项目 Fixture 中完成端到端生成和重复执行。

## 目标三：完成任务编排并达到发布标准

### 动态任务编排和 Context Compiler

### 目标状态

针对用户当前任务生成最小、阶段化、可失效的执行上下文。

### 首批任务场景

- 缺陷修复。
- 新功能。
- 重构。
- 性能。
- 安全。
- 数据库迁移。
- 依赖升级。
- 测试。
- UI 和可访问性。
- 文档。
- 发布。
- 线上故障。
- 技术探索。
- 代码审查。

### 能力范围

- 意图分类。
- 范围和风险判断。
- Fast、Standard 和 Rigorous 选择。
- 任务阶段图生成。
- 每阶段能力绑定。
- 使用条件、避免条件和降级。
- Context Capsule 编译。
- 来源摘要和失效条件。
- 用户修改任务计划。
- 阶段切换时重新编译。

### 运行方式

```bash
vibe plan "修复订单退款失败"
vibe explain-task "增加批量导入商品"
```

项目级 Skill 读取同一套工作流配置，为普通 Codex 对话提供软路由。

### 完成标准

- 简单任务可以选择零个额外能力。
- 高风险任务自动提高工作流强度。
- Capsule 不包含无关 Skill 正文或历史信息。
- 项目事实变化后旧 Capsule 自动失效。

### 验证和发布

### 场景评测

至少包含：

- 30 个简单任务。
- 30 个普通任务。
- 30 个高风险任务。
- 20 个不应调用额外能力的负样本。
- 20 个用户中途改变目标的样本。
- 20 个能力名称或描述冲突样本。

### 指标

- 意图分类准确率。
- 风险分类准确率。
- 能力 Recall@K。
- 无关能力选择率。
- Context Capsule 大小。
- 用户覆盖率。
- 错误权限请求率。
- 端到端配置成功率。
- Doctor 漂移检测率。

### 发布条件

- 所有核心命令有帮助信息。
- 安装和卸载流程清楚。
- 不依赖远程 Registry。
- 不自动安装第三方能力。
- 不读取 Secret 内容。
- 所有配置有 Schema。
- 关键流程有测试和 Fixture。
- 能在干净 Codex 环境和多 Skill 环境中运行。

## 后续能力方向

### 可信远程发现

### 目标状态

只针对本地能力缺口，从可信来源发现候选并解释推荐。

### 数据源

- Agent Skills 生态。
- skills.sh。
- MCP Registry。
- GitHub Repository Metadata。
- 官方 Marketplace。
- OSV 和 OpenSSF 安全信号。

### 范围

- 搜索和候选召回。
- Fit、Trust、Risk 和 Popularity 分离。
- 发布者和来源验证。
- License 和维护状态。
- 固定 commit、版本和内容摘要。
- 只推荐，不自动安装。

### 安装和硬路由

### 目标状态

支持经过审批的项目级能力安装，并真正控制当前会话可见工具。

### 范围

- 安装事务。
- 沙箱预检。
- 文件和权限 Diff。
- 脚本和 Prompt 静态扫描。
- 卸载和回滚。
- Host Adapter。
- MCP Gateway。
- 按阶段暴露工具。
- 权限扩大重新批准。

### 持续治理和生态

### 范围

- Practice Pack 迁移。
- Capability Manifest 版本迁移。
- 团队和组织策略。
- 私有能力目录。
- 多项目统一升级。
- Claude Code、Gemini、Copilot 和其他 Host Adapter。
- 根据真实结果生成策略调整建议。
- 可视化管理界面。

## 开发顺序原则

1. 先证明 Codex 入口和结构化输出。
2. 先做确定性仓库扫描，再做模型推断。
3. 先做本地能力，再做远程能力。
4. 先做软路由，再做硬路由。
5. 先做可解释推荐，再做自动安装。
6. 先有评测集，再优化检索和模型调用。
7. 先支持 Codex，再抽象多平台。

## 当前没有阻塞开发的问题

以下事项将在“建立可靠控制面”目标中验证，但不阻塞开始开发：

- Codex app-server 协议版本和事件兼容策略。
- app-server 与 `codex exec --output-schema` 的结构化输出边界。
- Codex 配置中 MCP 和 Plugin Inventory 的稳定读取接口。
- 临时命令名 `vibe` 的最终替代名称。

这些都存在明确回退方案，不需要继续扩大产品调研。
