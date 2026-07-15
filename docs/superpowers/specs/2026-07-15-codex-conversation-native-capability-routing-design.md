# Codex 原生能力选择与项目能力治理设计

**日期：** 2026-07-15  
**状态：** 修订后待用户复核
**仓库：** `local-skill-orchestrator`  
**替代方向：** 以 CLI 或自研 Router 接管 Codex 任务分类、Skill 选择和任务执行

## 摘要

本设计将产品主语明确为用户当前正在使用的 Codex。

Codex 原生负责理解用户任务、根据 Skill 描述隐式选择能力、按需加载 `SKILL.md`、使用 Tool 或 MCP，并在当前对话中执行任务。Vibe 不重新实现任务分类器，不要求每个项目操作先经过自研 Router，不生成第二套任务运行时，也不启动第二个 Codex。

Vibe 负责 Codex 原生能力选择之前和之外的项目级问题：理解项目需要哪些工程能力，盘点当前可用能力，识别缺口，推荐可信候选，征得用户同意后完成项目级安装和锁定，通过确定性 Hook、Doctor 和策略文件治理权限、供应链风险、漂移、升级、卸载与实际使用结果。

初始化完成后的标准体验是：

```text
用户继续正常与 Codex 对话
→ Codex 原生理解任务
→ Codex 根据 Skill description 隐式选择能力
→ Codex 按需加载完整 SKILL.md
→ Codex 在当前会话执行任务

如果缺少必要能力或依赖不可用
→ 项目能力管理 Skill 解释缺口并推荐候选
→ 用户确认
→ Vibe 在当前项目中安装、验证和锁定
→ Codex 继续原任务
```

CLI 是 Skill、Plugin 和 Hook 背后的内部确定性工具，不是用户的日常工作入口。

## 1. 设计依据

Codex 已经原生提供以下能力：

- 启动时读取项目和目录级 `AGENTS.md`。
- 扫描仓库、用户、管理员和系统级 Skills。
- 将 Skill 名称、描述和路径作为初始可发现元数据。
- 根据用户任务与 Skill `description` 进行隐式调用。
- 选中 Skill 后再读取完整 `SKILL.md`，实现渐进式披露。
- 通过 `agents/openai.yaml` 声明调用策略和 MCP 等工具依赖。
- 通过项目 Plugin 分发 Skills、MCP 配置和 Hooks。
- 通过 `UserPromptSubmit`、`PreToolUse`、`PermissionRequest`、`PostToolUse`、`Stop` 等 Hook 事件实现确定性检查和治理。

因此，本项目不得重复实现：

- 通用 Bug、功能、重构等任务语义分类器，作为每次对话的强制前置步骤。
- 与 Codex 原生 Skill 隐式调用竞争的 `selected_skills` 决策器。
- 每个项目操作都必须调用的自研 Router Skill。
- Skill 是否已读取的自研加载回执协议。
- 通过 CLI 启动另一个 Codex 执行当前任务。
- 用外部编排器替代当前 Codex 的阶段执行循环。

Vibe 应增强 Codex 的项目环境，而不是复制 Codex 的运行时大脑。

## 2. 产品目标

### 2.1 用户目标

用户只需要：

1. 安装 Vibe 的 Bootstrap Skill 或 Plugin。
2. 在 Codex 中表达“初始化这个项目的 AI 开发能力”。
3. 审阅项目事实、能力需求和缺口建议。
4. 确认需要安装的项目级能力。
5. 继续正常与 Codex 对话完成开发工作。

初始化后，用户不需要主动运行任何 `vibe` 命令，也不需要学习 Vibe 的内部模块。

### 2.2 产品职责

Vibe 负责：

- 确定性分析仓库事实。
- 通过对话确认无法从仓库得到的目标、阶段、风险和偏好。
- 推导项目需要的抽象工程能力。
- 盘点 Codex 当前可发现的 Skill、Plugin、MCP、Hook 和本地工具。
- 判断能力是否健康、兼容、可信且适用于当前项目。
- 识别项目能力缺口。
- 推荐本地优先、低权限、可解释的候选。
- 经用户确认后执行项目级安装、验证、锁定和回滚。
- 生成精简、项目特定的 `AGENTS.md` 和项目 Skills。
- 使用确定性 Hook 和策略阻止越权、漂移或未经批准的能力使用。
- 通过 Doctor、审计和实际结果持续治理能力生命周期。

### 2.3 非职责

Vibe 不负责：

- 接管 Codex 对话。
- 对每条用户消息进行强制语义分类。
- 代替 Codex 决定所有 Skill 是否触发。
- 改写每个用户 Prompt 后发送给第二个模型或线程。
- 执行用户业务任务。
- 构建通用 Agent Runtime。
- 要求用户通过 CLI 开始日常开发任务。

## 3. 总体架构

```text
初始化与治理平面                         正常任务执行平面

用户在 Codex 中请求初始化               用户在 Codex 中提出任务
          ↓                                      ↓
Bootstrap Skill / Plugin                 Codex 原生任务理解
          ↓                                      ↓
Vibe 项目分析与能力建模                  Skill description 隐式匹配
          ↓                                      ↓
本地 Inventory 与缺口解析                按需加载 SKILL.md
          ↓                                      ↓
用户确认项目级安装                       当前 Codex 使用 Tool / MCP
          ↓                                      ↓
生成 AGENTS / Skills / Lock              当前对话中完成任务
          ↓                                      ↓
Hooks / Doctor / Audit 持续治理           Hooks 做确定性安全和结果记录
```

两条平面共享项目能力配置，但职责严格分离：

- Codex 决定何时使用已经可发现的 Skill。
- Vibe 决定哪些能力可以进入项目、以什么版本和权限进入、是否仍然健康。

## 4. 初始化主链路

### 4.1 触发方式

用户在 Codex 中自然表达：

> 帮我初始化这个项目的 AI 开发能力。

Bootstrap Skill 被显式或隐式调用。它通过内部确定性工具完成扫描、解析和写入，不要求用户打开独立终端执行命令。

### 4.2 项目理解

Vibe 确定性识别：

- 语言、框架和包管理器。
- 构建、测试、Lint、Format 和类型检查命令。
- CI、容器、数据库、迁移、部署和 Monorepo 状态。
- 现有 `AGENTS.md`、Skills、Plugins、MCP 和 Hooks。
- Git 状态、项目阶段和可验证事实。

Codex 对话只确认仓库无法判断但会影响能力选择的问题：

- 项目目标和生命周期阶段。
- 是否处理真实用户、支付或敏感数据。
- 团队协作和发布要求。
- 是否允许项目级安装新能力。
- 用户明确的权限、隐私和生态偏好。

### 4.3 抽象能力需求

Vibe 先推导抽象需求，不先推荐具体产品。例如：

```text
repository-understanding
systematic-debugging
browser-verification
database-migration-review
security-review
release-verification
```

需求必须包含：

- 为什么项目需要。
- 适用任务和阶段。
- 不适用条件。
- 风险等级。
- 所需权限。
- 最小验证标准。
- 能力缺失时的降级边界。

### 4.4 Inventory 与解析

按以下优先顺序满足能力需求：

```text
Codex 内建能力
→ 仓库已有脚本和工具
→ 项目级已有 Skill / Plugin / MCP / Hook
→ 本机已有可信能力
→ 远程候选
```

选择原则：

- 项目事实高于通用最佳实践。
- 允许零个额外能力。
- 本地存在不等于必须选择。
- 低权限、确定性、本地方案优先。
- Skill 只负责工作流时，不安装不必要的 MCP。
- 热度只用于发现和同等候选排序。
- 每项选择、拒绝和延后都有原因。

### 4.5 用户审阅

Codex 在当前对话中展示精简结果：

```text
项目需要：
- systematic-debugging：已由本机 Skill 提供
- browser-verification：缺失
- security-review：项目上线前需要

建议：
1. 将 systematic-debugging 绑定到当前项目
2. 安装项目级 Playwright 验证能力
3. 暂不启用需要外部账号权限的浏览器 MCP
```

用户可以接受、拒绝、替换、延后或锁定决定。

### 4.6 项目级安装

用户同意后：

```text
展示文件、依赖和权限变化
→ 下载或复制到临时区域
→ 验证来源、版本和摘要
→ 静态安全扫描
→ 原子应用项目变化
→ 验证 Codex 可发现能力及其依赖
→ 更新项目能力 Lock
→ Doctor 验证
```

默认安装边界：

- `.agents/skills/`
- `.codex/plugins/` 或项目 Plugin 配置边界。
- `.codex/hooks.json` 或项目级 Hook 配置。
- `.ai-project/providers/`
- 项目依赖文件。
- 项目级 MCP 配置。

默认禁止修改：

- 用户全局 Codex 配置。
- 用户级 Skill 目录。
- 其他项目。
- Shell 全局配置。
- 系统包。

## 5. 正常 Codex 对话主链路

### 5.1 原生 Skill 选择

用户提出：

> 登录接口偶尔返回 500，帮我定位并修复。

Codex 原生根据可发现 Skill 的 `description` 判断是否隐式调用 `systematic-debugging`。选中后再读取完整 `SKILL.md`，并在当前会话中完成复现、根因分析、修复和验证。

Vibe 不参与每次正常匹配，也不要求先运行 `route-task`。

### 5.2 Vibe 如何提高原生匹配质量

Vibe 在初始化时负责生成或校验高质量 Skill 元数据：

- `name` 稳定且不与同项目 Skill 冲突。
- `description` 明确写出应该和不应该触发的条件。
- 关键任务词和适用场景前置，避免描述被截断后失去触发信息。
- `agents/openai.yaml` 正确声明隐式调用策略和 MCP 依赖。
- Skill 保持单一职责，不创建包罗万象的超级 Skill。
- 项目级 Skill 位于 Codex 原生扫描路径 `.agents/skills/`。

Vibe 应测试 Skill 描述的触发样本，而不是建立平行的运行时分类器。

### 5.3 `AGENTS.md` 的职责

`AGENTS.md` 保持精简，只保存每次任务都适用的项目事实和工程规则：

- 项目构建和验证命令。
- 仓库边界和关键目录。
- 高风险领域的确认要求。
- 项目完成标准。
- 能力治理和 Hook 不得绕过的规则。

不得在 `AGENTS.md` 中列出庞大任务路由表，也不得要求所有项目操作先调用 Vibe Router。

### 5.4 能力缺失时

当 Codex 发现：

- 需要的 Skill 不存在。
- Skill 声明的工具依赖不可用。
- MCP 未配置或未授权。
- 能力被项目策略禁用。
- 能力内容或权限发生漂移。

才调用项目级 `project-capability-manager` Skill。

建议描述：

```yaml
---
name: project-capability-manager
description: >
  Diagnose, recommend, install, replace, update, or remove project-local
  capabilities when Codex cannot complete a task with currently available
  skills or tools, when a declared dependency is missing or unhealthy, or
  when the user asks to manage project capabilities. Do not use for ordinary
  task classification or when existing capabilities are sufficient.
---
```

该 Skill 是异常与治理入口，不是所有任务的必经 Router。

## 6. 能力缺口、推荐和用户反馈

### 6.1 缺口确认顺序

```text
检查 Codex 内建能力
→ 检查仓库已有工具
→ 检查项目级能力
→ 检查本机可绑定能力
→ 确认真实缺口
→ 才允许发现远程候选
```

### 6.2 对话内推荐

Codex 说明：

- 为什么当前任务需要该能力。
- 不使用会失去什么验证或保障。
- 推荐候选的来源、权限、成本和维护状态。
- 会修改哪些项目文件。
- 如何卸载和回滚。

用户可以：

- 使用推荐方案。
- 查看详细来源和权限。
- 换一个更轻量的候选。
- 拒绝安装并说明原因。
- 仅当前任务延后。
- 当前项目永久不推荐。

### 6.3 反馈结构化

用户反馈保存为：

```yaml
scope: current-turn | current-task | current-project
action: reject | defer | constrain | replace | unlock
requirement: browser-verification
reason: avoid-large-browser-download
```

拒绝后必须重新解析候选或说明明确降级边界，不能简单终止任务。

### 6.4 安装失败

安装失败时：

- 回滚所有部分变化。
- 不把能力标记为可用。
- 保留脱敏失败原因。
- 提供重试、替换或不用三个方向。
- 当前 Codex 保持原任务上下文并根据用户选择继续。

## 7. Hook 治理

Hooks 用于确定性治理，不用于复制 Codex 的语义 Skill 选择。

### 7.1 `UserPromptSubmit`

可用于：

- 检测用户 Prompt 是否包含疑似 Secret，并阻止或提醒。
- 在能力状态存在严重漂移时注入简短诊断。
- 在项目能力依赖不可用时提示调用 `project-capability-manager`。

不得：

- 对每条 Prompt 重新完成通用任务分类。
- 注入完整能力目录或大型 Route Decision。
- 改写用户意图后发送给另一个 Codex。

### 7.2 `PreToolUse`

用于：

- 检查工具或命令是否违反项目与组织策略。
- 检查未经批准的项目外写入。
- 检查高风险命令、生产系统和外部写操作。
- 阻止使用已漂移或被禁用的能力入口。

### 7.3 `PermissionRequest`

用于补充：

- 请求权限的能力来源。
- 当前项目是否已批准。
- 权限是否较 Lock 扩大。
- 可用的低权限替代方案。

### 7.4 `PostToolUse`

用于记录脱敏结果：

- 哪项能力实际被使用。
- 是否成功。
- 是否产生返工。
- 验证是否通过。

不得保存 Secret、完整命令输出或与治理无关的代码内容。

### 7.5 `Stop`

用于检查：

- 项目定义的最低验证是否完成。
- 高风险任务是否缺少必要审查。
- 是否存在未处理的能力健康或权限问题。

Hook 只能执行确定性检查，不得声称能够证明业务实现正确。

### 7.6 Hook 信任

- 项目 Hook 只在受信任项目中启用。
- 新增或内容变化的 Hook 必须经过用户信任确认。
- Hook 内容固定摘要并进入项目 Lock。
- 未被信任的 Hook 不得静默运行。
- 管理策略可以强制企业级 Hook，但必须清楚标识来源。

## 8. 权限和供应链治理

### 8.1 无需新增确认

- 使用 Codex 内建只读能力。
- 使用已批准且健康的项目级 Skill。
- 运行项目已有的测试、Lint、类型检查和只读分析。

### 8.2 必须确认

- 安装新的项目级 Skill、Plugin、MCP、Hook 或依赖。
- 首次启用网络或外部系统访问。
- 能力版本升级导致文件或权限变化。
- 从项目范围扩大到用户或系统范围。
- 执行数据库迁移、部署、发布、外部写入或不可逆操作。

### 8.3 候选评估

每个候选分别评估：

- Fit：是否满足项目能力需求。
- Trust：来源、发布者和签名或摘要证据。
- Risk：权限、安装脚本、网络和数据边界。
- Maintenance：更新状态和兼容性。
- Cost：上下文、运行时、存储和维护成本。
- Popularity：只作发现信号。

### 8.4 生命周期

项目级能力必须支持：

- 查看安装原因和来源。
- Doctor 健康检查。
- 内容和权限漂移检测。
- 版本更新预览。
- 权限扩大重新审批。
- 替换、禁用、卸载和回滚。
- 根据真实使用结果建议降级或移除。

## 9. 项目产物

初始化后生成或维护：

```text
AGENTS.md
.ai-project/
├── blueprint.yaml
├── capability-requirements.yaml
├── capabilities.yaml
├── capabilities.lock
├── policy.yaml
├── decisions.md
├── quality-gates.md
└── capability-outcomes.yaml

.agents/skills/
├── project-capability-manager/
│   ├── SKILL.md
│   └── references/
└── <selected-project-skills>/

.codex/
├── config.toml                 # 仅项目受信任配置
└── hooks.json                  # 可选，用户审阅并信任
```

### 9.1 `AGENTS.md`

只包含稳定项目规则、命令、风险边界和完成标准。保持简短，避免与具体 Skill 正文重复。

### 9.2 `capability-requirements.yaml`

记录项目需要哪些抽象能力及原因，不绑定供应商。

### 9.3 `capabilities.yaml`

记录抽象需求与当前具体提供者的绑定。

### 9.4 `capabilities.lock`

记录：

- 能力 ID 和类型。
- 项目入口。
- 来源与发布者。
- 版本或 Commit。
- 内容摘要。
- 权限。
- 依赖和验证状态。
- Hook 信任摘要。

## 10. 现有实现迁移

### 10.1 保留

- 仓库扫描和事实模型。
- Inventory 与 Capability Adapter。
- Practice Packs 和抽象需求解析。
- 远程候选、评分、来源验证和安全扫描。
- 项目级事务安装、卸载、更新和回滚。
- Doctor、漂移、审计和组织策略。
- 结果记录与能力校准。
- Codex app-server 集成作为诊断、初始化对话和测试工具。

### 10.2 重构

- Bootstrap Skill 从“指导用户运行 CLI”改为“在 Codex 对话中调用内部工具完成初始化”。
- `project-development` 改为窄职责 `project-capability-manager`。
- 能力解析输出增加 Codex 原生 Skill 入口、`agents/openai.yaml` 和项目 Hook 元数据。
- 生成器输出精简 `AGENTS.md`，并生成可被 Codex 原生扫描的 `.agents/skills/`。
- 评测重点从自研任务分类准确率改为 Skill 描述触发质量、缺口识别和治理正确性。

### 10.3 退出主链路

- `vibe run` 不再是用户任务入口。
- 参数繁重的 `vibe plan` 不再是日常入口。
- 自研 `_ROUTE_CANDIDATES` 不再决定 Codex 正常任务使用哪些 Skill。
- CLI 驱动的阶段执行和第二 Codex 线程路径进入兼容期并标记 deprecated。
- 自研硬路由不再作为所有任务的默认目标；仅保留对高风险工具和权限的 Hook 或宿主治理研究。

### 10.4 CLI 定位

CLI 保留用于：

- Skill 或 Plugin 内部调用。
- CI 和确定性测试。
- Doctor 和审计诊断。
- 无交互自动化。
- 开发者调试。

用户文档不得把 CLI 作为初始化后日常开发的主要体验。

## 11. 分阶段交付

### 阶段一：Codex 原生 Skill 体验

- 重写 Bootstrap Skill。
- 生成精简 `AGENTS.md`。
- 生成 `project-capability-manager`。
- 将选中能力安装或绑定到 `.agents/skills/`。
- 为 Skill 生成或校验高质量 `description` 和 `agents/openai.yaml`。
- 删除文档中要求用户通过 `vibe run` 完成任务的主流程。

### 阶段二：对话内缺口补全

- Skill 或工具依赖缺失时触发能力管理 Skill。
- 对话内解释和推荐候选。
- 用户确认后项目级事务安装。
- 安装验证后由当前 Codex 继续原任务。
- 支持拒绝、替换、延后和项目级锁定。

### 阶段三：Hook 治理

- 项目级 Hook 安装与信任审阅。
- Secret 检查。
- 工具权限与项目外写入检查。
- 能力漂移阻止。
- 使用结果和质量门禁记录。

### 阶段四：持续治理

- Doctor 与能力健康状态联动。
- 权限扩大重新审批。
- 使用结果驱动的保留、替换或移除建议。
- 组织级私有目录和策略。

## 12. 测试策略

### 12.1 Codex 原生 Skill 发现

验证：

- 项目 Skills 位于 Codex 原生扫描位置。
- Skill 元数据有效。
- `allow_implicit_invocation` 符合策略。
- MCP 依赖声明正确。
- 同名冲突被检测并解释。
- 大量 Skill 时关键描述仍能进入发现预算。

### 12.2 Skill 触发评测

使用真实 Codex 环境和固定样本验证 Skill 描述，而不是以 Vibe 分类结果代替 Codex 行为。

至少覆盖：

- 30 个应触发调试、测试、安全、数据库或发布 Skill 的任务。
- 30 个不应触发这些 Skill 的问答与简单任务。
- 20 个描述相似但职责不同的 Skill 冲突样本。
- 20 个用户显式指定或禁止某 Skill 的样本。

指标：

- 隐式触发召回率。
- 错误触发率。
- 同类 Skill 冲突率。
- 不相关 Skill 上下文加载率。
- 用户显式覆盖成功率。

### 12.3 初始化和能力缺口

验证：

- 相同项目事实产生稳定抽象需求。
- 内建和仓库能力优先。
- 能力充分时不推荐额外安装。
- 缺口解释包含必要性、权限和成本。
- 未经确认不安装。
- 默认只写当前项目。
- 用户拒绝后重新解析或明确降级。

### 12.4 安装和供应链

验证：

- 来源、版本和摘要固定。
- 恶意 Skill、MCP、Plugin 和 Hook 被拦截。
- 部分失败完整回滚。
- 安装后 Codex 能原生发现能力。
- 权限扩大要求重新批准。
- 卸载后项目配置和发现结果一致。

### 12.5 Hook

验证：

- 未信任项目 Hook 不运行。
- Hook 变更后需要重新信任。
- `PreToolUse` 能阻止策略违规操作。
- `PermissionRequest` 正确解释权限来源。
- `PostToolUse` 只记录脱敏治理数据。
- Hook 不对每条 Prompt 重复进行通用任务分类。
- 禁用 Hook 后 Codex 原生 Skill 使用仍然正常。

### 12.6 用户体验

真实环境端到端验收必须证明：

- 用户初始化后只通过 Codex 对话工作。
- 用户不需要输入 `vibe` 命令。
- 普通任务由 Codex 原生选择和加载 Skill。
- 缺少能力时才出现 Vibe 推荐。
- 用户确认后项目级安装并继续原任务。
- 用户拒绝后可以替换、降级或不用。
- 正常任务没有第二个 Codex 进程或线程。

## 13. 发布验收标准

1. 初始化通过 Codex 对话完成，CLI 对用户不可见。
2. 生成的项目 Skill 能被 Codex 原生发现。
3. 真实 Codex 能根据 Skill 描述隐式选择合适能力。
4. Vibe 不参与每次正常任务的通用语义分类。
5. Vibe 不启动第二个 Codex 执行用户任务。
6. 能力充分时，正常对话没有额外 Vibe 路由步骤。
7. 能力缺失或不健康时，项目能力管理 Skill 才介入。
8. 用户同意后只在当前项目安装、验证和锁定能力。
9. 用户拒绝后支持替换、降级或不用。
10. Skill、Plugin、MCP 和 Hook 的来源、摘要、权限和健康状态可审计。
11. 未经确认的安装率为零。
12. 项目外非授权写入率为零。
13. Hook 不复制 Codex 原生 Skill 选择逻辑。
14. 现有安全、回滚、漂移和组织策略能力不倒退。
15. 通过真实 Codex 环境人工验收，而不仅依赖 Fake 测试。

## 14. 最终产品定义

> Vibe 是 Codex 的项目能力初始化器、供应链管理器和治理层。它帮助项目获得一套适合当前仓库、可信、完整、可维护的 Skills、Tools、MCP、Plugins 和 Hooks；正常任务仍由 Codex 原生理解、按需选择能力并在当前对话中执行。

Vibe 不再定义为任务路由器、外部 Agent 编排器或 Codex Launcher。
