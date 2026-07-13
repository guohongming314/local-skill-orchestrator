# AI 编程项目能力初始化器调研报告

**日期：** 2026-07-13  
**状态：** 调研完成  
**范围：** AI 编程实践、项目初始化、Skills、MCP、Plugins、Tools、安全和能力发现

## 执行摘要

这个产品不应该只是 Skill 搜索器、热度排行榜、MCP 安装器或针对每次请求临时选择 Skill 的路由器。

它应该成为一个本地优先的 AI 开发环境架构师，负责：

1. 理解仓库、项目目标、生命周期阶段、风险和用户偏好。
2. 先定义项目需要怎样的工程行为，再选择具体扩展包。
3. 优先复用兼容、可信的本地能力。
4. 只有存在明确能力缺口时，才从可信外部来源寻找候选。
5. 根据适配度、质量、维护状态、权限、供应链风险和社区采用情况评估候选。
6. 生成可解释、可编辑、可复现、可升级的项目级开发配置。

产品最核心的原则是：

> 推荐一套好的工程行为，而不是推荐一堆 AI 扩展。

## 调研范围

本次调研覆盖：

- OpenAI Codex、Claude Code、Gemini CLI、GitHub Copilot 和 Cursor 的官方实践。
- SWE-bench、SWE-agent、METR、DORA 和开发者信任度研究。
- Aider、Continue、Cline、Roo Code、OpenHands、Superpowers、Spec Kit、OpenSpec、BMAD 和 Taskmaster。
- Agent Skills、skills.sh、MCP Registry、Plugins、Hooks 和 CLI Tools。
- `create-*`、Yeoman、Nx、Backstage、Dev Containers、Nix、Devbox、Cookiecutter 和 Copier 等项目生成与持续演进系统。

## 调研发现

### 1. 不同 AI 开发能力具有不同职责

| 能力载体 | 最适合解决的问题 |
|---|---|
| 仓库指令 | 稳定的项目规则、命令、约束和完成标准 |
| Skill | 按需加载的专业知识、判断规则和多步骤工作流 |
| Tool | 搜索、构建、测试、格式化和 Git 等确定性本地操作 |
| MCP | 外部系统、实时数据和授权操作的结构化访问 |
| Agent | 隔离上下文、独立角色、独立权限或并行工作 |
| Hook | 确定性拦截、策略执行、验证和自动化 |
| Plugin | 多种能力的组合分发和生命周期管理 |

初始化器必须先判断某个需求应该由哪种能力载体解决。如果稳定的本地 CLI 已经能够完成工作，再安装 MCP 只会增加上下文、权限和供应链成本。

### 2. 成功系统都在编码开发过程，而不只是生成代码

优秀的 AI 编程工作流普遍强调：

- 修改代码前先理解仓库。
- 实现前澄清含糊需求。
- 根据任务风险决定是否需要计划或规格。
- 采用小批量、可恢复的修改。
- 执行项目特定的验证命令。
- 不仅依赖实现 Agent 自己声明成功，还要独立审查结果。
- 保持长期指令精简，只在需要时加载专业指导。

因此，产品首先应该配置一套开发策略，而不是单纯安装开发辅助工具。

### 3. AI 使用率不能证明真实生产力

研究表明，真实仓库开发依赖环境配置、代码导航、测试执行、工具反馈和审查质量。用户主观感受到的速度和生成代码量都不是可靠的成功指标。

产品更应该衡量：

- 首次验证通过率。
- 用户接受的 Diff 比例。
- 返工次数。
- 回归缺陷率。
- 代码审查发现的问题。
- 失败后的恢复时间。
- 能力实际使用率和弃用率。

### 4. 热度是发现信号，不是信任信号

Stars、安装量、下载量和排行榜可以帮助发现候选，但无法证明某项能力安全、持续维护、兼容当前环境或适合当前项目。

外部候选在被推荐或安装前，必须分别进行适配度、信任度和风险评估。

### 5. 初始化器必须与项目保持长期关系

传统脚手架提供了良好默认值和低门槛初始化体验，但通常在项目生成后就失去了对项目状态的理解。Nx、Copier、Nix、Devbox、Backstage 和 Dev Containers 证明了以下设计的价值：

- 声明式期望状态。
- 锁文件。
- Dry-run。
- 可组合能力。
- 版本化迁移。
- 明确的文件管理边界。
- 漂移检测。

项目初始化器需要保存项目意图、决策、来源、版本、用户覆盖项和受管理资源。

### 6. 能力价值取决于使用策略，而不只是是否安装

一项高质量能力如果在错误任务、错误阶段或错误权限下使用，仍然会降低开发质量。

因此，每项能力除了安装元数据，还必须定义：

- 适用于哪些任务场景。
- 不适用于哪些任务。
- 应该在哪个工作流阶段使用。
- 应该先于或晚于哪些能力。
- 需要什么输入和权限。
- 输出如何验证。
- 能力不可用时如何降级。

产品必须内置可扩展的任务场景模型，至少覆盖缺陷修复、新功能、重构、性能、安全、数据库迁移、依赖升级、测试、UI、文档、发布、线上故障、技术探索和代码审查。

初始化阶段回答“项目拥有哪些能力”，任务执行阶段回答“当前任务如何正确使用这些能力”。两者缺一不可。

## 工程品味

产品的默认推荐应遵循以下原则：

1. 项目事实高于通用最佳实践。
2. 用户明确决策高于系统推荐，但不能突破安全边界。
3. 先理解项目，再推荐技术或能力。
4. 先选择抽象能力，再选择具体包或供应商。
5. 优先使用 Agent 内建能力。
6. 优先使用仓库已有工具和脚本。
7. 优先使用兼容、可信、经过验证的本地能力。
8. 选择最小充分能力集合。
9. 验证能力优先于生成能力。
10. 确定性约束优先于提示词提醒。
11. 根据任务和项目风险调整流程强度。
12. 热度只用于发现和同等候选之间的排序。
13. 解释每项推荐及其成本。
14. 让每项非强制能力都可以替换和卸载。
15. 随着项目变化持续更新配置。

## 哪些能力应该成为项目基础

调研不支持把 CodeGraph、Claude-Mem 或任何具体第三方产品设为所有项目的默认依赖。

产品应该定义的是分层能力基线，而不是固定工具全家桶。

### 第一层：所有项目默认需要

这些能力应进入 `base-engineering`，并尽量使用 Agent 内建能力和仓库已有工具完成：

- 仓库文件和目录探索。
- 文本和符号搜索。
- Git 状态、Diff 和恢复点。
- 构建、运行和依赖安装方式。
- 定向测试和完整质量检查。
- Lint、Format 和 Typecheck。
- 项目规则和完成标准。
- Secret 防护和高风险操作审批。

这一层默认不要求安装任何第三方 Skill、MCP 或 Plugin。

### 第二层：满足条件时强烈推荐

这些是能力类型，不绑定具体产品：

| 条件 | 推荐能力 | 可能的提供者 |
|---|---|---|
| 大型仓库、Monorepo、跨模块调用复杂 | 代码关系和依赖分析 | CodeGraph、语言服务器、代码索引工具 |
| 项目会持续很多会话，决策经常丢失 | 项目连续性和决策记忆 | 仓库内决策记录、项目记忆插件、Claude-Mem |
| Web 项目包含关键交互流程 | 浏览器端到端验证 | Playwright CLI、测试 Skill、浏览器工具 |
| 涉及数据库 Schema | 数据库迁移审查 | 数据库工具、迁移 Skill、Schema 检查器 |
| 涉及认证、支付或敏感数据 | 安全审查 | 安全 Skill、静态分析、专门审查 Agent |

### 第三层：用户确认后才启用

- 保存完整对话历史的长期记忆系统。
- 访问外部账号、Issue、设计稿或生产数据的 MCP。
- 自动执行 Hooks。
- 浏览器控制。
- 云资源、数据库或部署写权限。
- 修改全局 Agent 配置的 Plugin。

### CodeGraph 是否真的需要

代码图和仓库结构化索引对大型、陌生和关系复杂的代码库具有明确价值。相关研究和工程实践表明，编码 Agent 的仓库导航、依赖理解和工具接口质量会显著影响任务结果。

但这不能推出“所有项目都应该安装 CodeGraph”：

- 小型项目使用 `rg`、语言服务器和正常文件探索通常已经足够。
- 代码图的价值随仓库规模、语言支持、索引质量和任务类型变化。
- 索引服务会增加初始化时间、存储、维护和工具上下文成本。
- 如果本地 CodeGraph 已经可用且兼容，应优先复用；如果没有，应先确认项目确实存在结构化代码理解缺口。

因此推荐规则是：

```text
小型或结构简单仓库             不默认推荐
大型仓库或 Monorepo            推荐代码关系分析能力
频繁跨模块修改                 推荐代码关系分析能力
普通搜索多次无法定位影响范围   升级推荐
```

### Claude-Mem 是否真的需要

跨会话记忆对长期项目、重复上下文恢复和历史决策检索可能有价值，但长期记忆不是无条件收益。

主要风险包括：

- 记忆内容过时后继续影响新任务。
- 保存对话和代码信息带来的隐私问题。
- 检索出不相关历史，污染当前上下文。
- 用户不知道系统保存了什么以及如何删除。
- 将本应进入仓库文档的稳定决策留在私有记忆中。

因此，应先使用可审查、可进入 Git 的项目记忆：

- `AGENTS.md`。
- `decisions.md`。
- ADR。
- Blueprint 和项目配置。

只有在项目确实跨越大量会话，而且用户需要检索未结构化历史时，才推荐 Claude-Mem 一类长期记忆产品。

推荐规则是：

```text
稳定项目规则和架构决策          写入仓库，不依赖记忆插件
短期或一次性项目                不推荐长期记忆
长期个人项目、频繁跨会话恢复    可选推荐
团队共享项目                    优先仓库文档和共享系统
保存完整对话或敏感内容          必须明确批准
```

## 用户不知道能力时如何处理

初始化器不能直接询问：

```text
是否安装 CodeGraph？
是否启用 Claude-Mem？
```

用户可能不知道这些产品，也不应该为了完成初始化而学习整个生态。

系统应该询问项目结果和使用场景：

```text
这个仓库是否很大，或者经常需要跨多个模块追踪调用关系？
你是否经常在不同会话中继续同一个项目，并需要恢复之前的讨论和临时结论？
```

然后用普通语言给出推荐：

```text
我建议增加“代码关系分析”能力。

原因：这个仓库包含多个服务和共享模块，普通文本搜索难以可靠判断修改影响范围。

本地可用实现：CodeGraph。
它会在本地建立代码关系索引，不会替代现有搜索工具。

你可以：
1. 使用推荐方案
2. 只使用现有搜索工具
3. 查看详细权限和成本
```

如果用户没有相关需求，系统应略过该能力，不展示无关产品列表。

## 能力本体模型

解析器应该独立于具体供应商来描述项目需要的能力。

### 生命周期能力

- 产品探索和需求澄清。
- 规格和验收标准。
- UI、UX、可访问性和内容设计。
- 架构、API 和数据建模。
- 前端、后端、移动端、CLI、数据、AI 和基础设施开发。
- 单元、集成、端到端、性能、可访问性和安全测试。
- 代码审查和架构审查。
- CI/CD、部署、回滚、可观测性、故障处理、备份和成本治理。

### 风险能力

项目包含以下内容时，应自动提高工作流的严格程度：

- 身份认证或权限控制。
- 支付。
- 个人数据或受监管数据。
- 文件上传。
- 外部 Webhook。
- 任意代码执行。
- 数据库 Schema 修改。
- 基础设施修改。
- 生产部署或破坏性操作。

### 能力形态

```text
knowledge       -> Skill
workflow        -> Skill 或 Agent
tool            -> CLI 或内建 Tool
connector       -> MCP
automation      -> Hook 或 CI
agent           -> Subagent
bundle          -> Plugin
repository-rule -> AGENTS.md 或对应平台文件
```

## 能力解析策略

按照以下顺序寻找能力：

1. 当前 Agent 的内建能力。
2. 仓库已有工具和脚本。
3. 已有项目级能力。
4. 用户级本地能力。
5. 已配置且可信的 MCP 或 Plugin。
6. 组织批准的能力目录。
7. 官方 Marketplace 和 Registry。
8. 已验证发布者。
9. skills.sh 等社区索引。
10. 精选列表、GitHub 搜索和普通 Web 搜索。

本地存在不代表必须选择。本地能力可能不兼容、已经损坏、权限过大、长期未维护、与现有能力重复或违反项目策略。

## 候选评估

### 硬性过滤

直接排除以下候选：

- 与用户要求或仓库策略冲突。
- 不支持当前 Agent、操作系统或运行时。
- License 不兼容。
- 权限超过项目策略。
- 无法固定到不可变版本或摘要。
- 包含无法审计的安装行为。
- 请求无关凭据或要求关闭安全控制。
- MCP 权限范围不透明或允许无限制命令执行。
- 已知存在恶意行为、已经被接管，或已停止维护且存在更安全的活跃替代品。

### 适配分 `FitScore`

```text
任务能力匹配             30
技术栈匹配               15
项目生命周期匹配         10
运行时兼容               10
与现有能力互补           10
验证工作流完整           10
用户偏好                  5
维护状态                  5
社区采用                  5
```

### 信任分 `TrustScore`

```text
来源真实性               15
发布者身份               10
不可变版本               10
内容可审计               10
最小权限                 15
供应链来源证明           10
维护和响应               10
安全历史                 10
License 和治理            5
测试和发布流程            5
```

### 风险分 `RiskScore`

```text
仓库写入或命令执行       15
外部写权限               15
凭据访问                 15
安装脚本                 10
未锁定依赖               10
后台进程                 10
提示注入攻击面           10
数据外传攻击面           10
维护异常                  5
```

热度最多只应占最终排序的 10%–15%，主要用于适配度和信任度相近的候选之间打破平局。

## 权限模型

| 等级 | 示例 | 默认行为 |
|---|---|---|
| L0 | 内建工具和已有只读能力 | 自动使用 |
| L1 | 仅包含 Markdown 的项目级 Skill | 一次确认 |
| L2 | 可执行 Skill、安装 CLI、只读 MCP | 展示来源、版本、文件和权限 |
| L3 | 外部写入、凭据、Hooks、浏览器控制、全局修改 | 逐项批准 |
| L4 | 来源不可验证、访问无关 Secret、绕过安全机制 | 阻止 |

任何权限扩张都必须重新获得用户批准。

## 推荐产品架构

```text
CLI
├── init
├── inspect
├── explain
├── doctor
├── diff
├── reconcile
├── update
└── audit

对话引擎
├── 访谈规划器
├── 决策记录器
├── 推荐解释器
└── 审阅工作流

项目模型
├── Blueprint
├── 策略
├── 决策
├── 用户覆盖
└── 能力需求

解析器
├── 本地能力盘点
├── 远程能力发现
├── 兼容性求解
├── 适配度评估
├── 信任评估
└── 风险评估

执行引擎
├── 虚拟变更树
├── Dry-run
├── 事务管理器
├── Adapter 运行时
└── 验证执行器

生命周期治理
├── Lockfile
├── 漂移检测器
├── 迁移引擎
├── 冲突解决器
└── 审计日志
```

## 推荐项目产物

```text
project/
├── AGENTS.md
├── .ai-project/
│   ├── blueprint.yaml
│   ├── capabilities.yaml
│   ├── capabilities.lock
│   ├── policy.yaml
│   ├── decisions.md
│   └── quality-gates.md
└── .agents/
    └── skills/
        └── project-development/
            ├── SKILL.md
            └── references/
                ├── capability-routing.md
                └── quality-gates.md
```

Blueprint 是唯一事实来源。不同 Agent 平台的项目指令文件和项目级 Skill 都是根据 Blueprint 生成的视图。

## 实践包

工程品味应该维护为版本化的 Practice Packs，而不是写进一个巨大的 Prompt。

示例：

- `base-engineering`
- `open-source-library`
- `web-application`
- `production-web`
- `typescript`
- `react`
- `backend-api`
- `database-backed`
- `security-sensitive`
- `ai-agent`
- `mobile-application`
- `cli-tool`

每条实践需要定义适用条件、推荐强度、理由、证据、例外和验证方法。

```yaml
id: verify-critical-user-flows
applies_when:
  project.delivery: web
  project.phase: [beta, production]
strength: strongly-recommended
requirement:
  capability: browser-verification
reason: 核心用户流程需要在真实浏览器环境中验证。
exceptions:
  - disposable-prototype
verification:
  capability_present: true
  command_works: true
```

推荐强度：

```text
required               必须
strongly-recommended   强烈推荐
recommended            推荐
optional               可选
discouraged            不建议
forbidden               禁止
```

## 交付阶段

### 第一阶段：本地能力初始化

- 分析空白目录和已有仓库。
- 通过对话确认目标、风险、约束和偏好。
- 扫描本地 Skills、Tools、MCP、Plugins、Hooks 和项目指令。
- 建立项目模型、风险模型和能力需求模型。
- 解析本地能力。
- 输出能力缺口。
- 生成 Blueprint、项目指令、薄项目 Skill 和 Lockfile。
- 支持用户覆盖和 `doctor` 检查。
- 不自动安装任何远程内容。

### 第二阶段：可信能力发现

- 查询社区和官方能力目录。
- 收集仓库、发布者、维护状态、License 和采用情况数据。
- 固定不可变版本和内容摘要。
- 扫描 Skill 指令和 MCP 权限。
- 对比候选并解释推荐理由。

### 第三阶段：安全安装

- 增加 Dry-run 和虚拟变更树。
- 展示安装 Diff 和权限变化。
- 使用事务方式应用修改。
- 在条件允许时增加来源证明、SBOM、签名和安全检查。
- 验证安装结果，并支持卸载和回滚。

### 第四阶段：持续治理

- 检测环境、项目、配置和实践漂移。
- 增加迁移和状态协调。
- 跟踪能力使用情况、返工、验证失败和用户覆盖。
- 支持团队和组织策略。

## 第一版明确不做

- 自动安装任意 GitHub 仓库。
- 仅根据 Stars 或安装量排序。
- 为每个项目安装一整套 Skills。
- 连接所有可用 MCP。
- 没有明确价值时用 MCP 替换稳定本地 CLI。
- 静默修改全局 Agent 配置。
- 覆盖已有项目指令文件。
- 自动执行未知 Skill 中的脚本。
- 读取或保存凭据内容。
- 将第三方 Skill 内容复制进生成的项目 Skill。
- 不锁定版本就跟随上游可变分支。
- 要求所有任务都使用完整规格或多 Agent 工作流。
- 仅根据生成代码量或某一组测试通过就声明成功。

## 推荐产品定义

> 一个面向编码 Agent 的本地优先项目能力初始化与治理系统。它将项目目标、仓库事实、风险和用户偏好转换成一组最小、可信、权限受控、可复现的 Instructions、Skills、Tools、MCP、Agents、Hooks 和 Plugins，同时保留用户控制权并持续验证配置结果。

## 主要资料来源

- OpenAI Codex 文档：<https://developers.openai.com/codex/>
- Claude Code 最佳实践：<https://code.claude.com/docs/en/best-practices>
- Gemini CLI 文档：<https://github.com/google-gemini/gemini-cli/tree/main/docs>
- GitHub Copilot CLI 最佳实践：<https://docs.github.com/en/copilot/how-tos/copilot-cli/cli-best-practices>
- Cursor Agent 最佳实践：<https://cursor.com/blog/agent-best-practices>
- SWE-bench：<https://www.swebench.com/>
- SWE-agent：<https://github.com/SWE-agent/SWE-agent>
- METR 资深开发者研究：<https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/>
- DORA 研究：<https://dora.dev/research/>
- Model Context Protocol：<https://modelcontextprotocol.io/>
- skills.sh：<https://skills.sh/>
- Superpowers：<https://github.com/obra/superpowers>
- Spec Kit：<https://github.com/github/spec-kit>
- OpenSpec：<https://github.com/Fission-AI/OpenSpec>
- BMAD Method：<https://github.com/bmad-code-org/BMAD-METHOD>
