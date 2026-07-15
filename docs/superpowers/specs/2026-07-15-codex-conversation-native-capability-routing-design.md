# Codex 对话内项目能力自动路由设计

**日期：** 2026-07-15  
**状态：** 已批准，待实施规划  
**仓库：** `local-skill-orchestrator`  
**修正对象：** `2026-07-13-project-ai-capability-bootstrapper-design.md` 中以 CLI 驱动任务执行的主链路

## 摘要

本设计将产品主入口从外部 CLI 编排器改回用户当前正在使用的 Codex 对话。

用户完成项目初始化后，只需继续正常与 Codex 对话。当请求涉及修改项目、运行项目命令、变更依赖或配置、访问外部系统、代码审查或发布等项目操作时，Codex 必须在第一次产生副作用前进入项目能力路由：识别任务场景与风险，查询项目级已验证能力，选择并实际加载最小充分能力集合，然后由当前 Codex 在原对话中继续执行。

当项目缺少必要能力时，系统在当前对话中解释缺口、推荐候选并等待用户确认。用户同意后，系统仅在当前项目范围内完成安装、验证和重新路由；用户拒绝后，根据反馈替换候选、降级方案或不使用该能力。

CLI 保留为 Router Skill 背后的确定性内部接口，不再是用户完成日常开发任务的主入口。正常流程不得启动第二个 Codex 进程或线程。

## 1. 产品目标

### 1.1 用户体验目标

初始化完成后的标准体验是：

```text
用户在 Codex 中提出项目任务
→ 系统自动判断是否需要路由
→ 简短告知识别结果和选中能力
→ 当前 Codex 按需加载 Skill、Tool、MCP 或 Plugin 能力
→ 当前 Codex 在原对话中执行任务
→ 目标、范围、风险或阶段变化时自动重新路由
```

用户不需要知道或主动运行 `vibe inspect`、`vibe plan`、`vibe run`、`vibe doctor` 等命令。内部命令只作为项目 Skill、确定性工具接口和诊断手段存在。

### 1.2 路由范围

仅项目操作进入自动路由，包括：

- 修改、创建或删除项目文件。
- 调试、实现、重构、测试和代码审查。
- 修改依赖、构建配置、数据库、基础设施或发布配置。
- 运行项目命令或具有项目副作用的生成器。
- 访问项目相关外部系统。
- 准备部署、发布或回滚。

以下请求不进入路由：

- 概念问答。
- 解释已有代码但不执行项目操作。
- 仅讨论技术方案。
- 总结文档或普通闲聊。

讨论转为实施时，必须在第一次项目副作用前进入路由。

### 1.3 用户可见性

正常路由采用简短提示，不等待确认：

> 已识别为 Bug 修复，将使用 systematic-debugging 和项目测试工具，先复现、定位根因，再实施修复和回归验证。

只有新增能力、权限扩大、网络或外部访问、高风险操作需要用户确认。

### 1.4 核心约束

- 当前 Codex 是唯一任务执行者。
- 不得通过 `vibe run` 或其他路径启动第二个 Codex 执行任务。
- 普通问答不得被能力路由打断。
- 项目操作默认路由。
- 新增能力必须由用户确认。
- 新能力默认只安装到当前项目。
- 用户拒绝后必须支持替换、降级或不用。
- 路由选择最小充分能力集合。
- Skill 负责指导；确定性代码负责权限、安装、写入、验证和审计。

## 2. 架构

### 2.1 总体结构

```text
用户请求
  ↓
当前 Codex 判断是否属于项目操作
  ↓ 是
project-router Skill
  ↓
确定性路由内核
  ├─ 读取项目事实与任务状态
  ├─ 识别任务场景、范围和风险
  ├─ 查询项目级能力清单
  ├─ 选择最小能力集合
  ├─ 计算权限和失效条件
  └─ 返回 Route Decision
  ↓
当前 Codex 简短说明路由结果
  ↓
当前 Codex 按需加载 Skill 或调用工具
  ↓
当前会话中执行任务
```

### 2.2 职责边界

#### 当前 Codex

负责：

- 与用户保持原有对话。
- 判断消息是否属于项目操作。
- 调用 `project-router`。
- 加载路由结果指定的 Skill。
- 使用选中的 Tool、MCP 或 Plugin 能力。
- 修改代码、运行验证和汇报结果。
- 在失效事件发生时重新路由。

#### `project-router` Skill

负责：

- 规范项目操作的路由入口。
- 调用确定性路由内核。
- 用一句话解释路由结果。
- 按路由结果加载具体 Skill。
- 处理能力缺口、安装确认和用户反馈。
- 维护当前任务的路由状态。

Router Skill 不得自行扫描全局能力、绕过项目能力锁、计算权限或启动另一个 Codex。

#### 确定性路由内核

负责：

- Schema 验证。
- 项目事实、能力清单和任务状态读取。
- 能力兼容性与健康状态过滤。
- 风险下限和权限计算。
- 选中、延后、拒绝及其原因。
- Route Decision 和失效摘要生成。
- 能力缺口与候选推荐。
- 项目级安装、验证、锁定、卸载和回滚。

它只返回决策，不执行用户的业务任务。

#### 项目配置

项目配置保存长期、可审查、可复现的状态：

```text
.ai-project/
├── blueprint.yaml
├── capabilities.yaml
├── capabilities.lock
├── routing-policy.yaml
├── decisions.md
└── task-state/              # 默认忽略或迁移至平台状态目录

.agents/skills/project-router/
├── SKILL.md
└── references/
    ├── routing-policy.md
    ├── capability-catalog.md
    └── quality-gates.md
```

## 3. 稳定触发机制

纯 Skill 语义触发不能保证每次项目操作都稳定进入路由，因此采用多层保障。

### 3.1 `AGENTS.md` 项目规则

初始化器写入受管理区块：

```markdown
<!-- vibe:router:start -->
## Project operation routing

A project operation is any request that may modify files, run project
commands, change dependencies or configuration, access external systems,
review code, or prepare a release.

Before starting a project operation:

1. Load the `project-router` Skill.
2. Obtain a route decision for the current task.
3. Briefly tell the user which workflow and capabilities were selected.
4. Load each selected Skill before following its instructions.
5. Re-route when the route decision's invalidation conditions occur.

Do not route questions or discussions that perform no project operation.
Do not start another Codex process or delegate execution to `vibe run`.
<!-- vibe:router:end -->
```

### 3.2 Router Skill 触发描述

```yaml
---
name: project-router
description: >
  Route every project operation before Codex modifies files, runs project
  commands, changes dependencies or configuration, accesses external
  systems, reviews code, or prepares a release. Do not use for questions
  and discussions that perform no project operation.
---
```

### 3.3 第一次副作用前自检

在以下动作前，当前 Codex 必须确认存在有效 `route_id`：

- 编辑、创建或删除文件。
- 执行项目命令。
- 安装依赖或能力。
- 调用有副作用或额外权限的 MCP。
- 修改 Git、数据库、云资源或外部系统。

不存在有效路由时，必须先调用 Router。未来若 Codex 提供稳定的 pre-tool 或 pre-edit Hook，该检查应提升为宿主级硬门禁。

### 3.4 项目级固定能力入口

任务运行只能选择：

- 项目内已安装并锁定的能力。
- 已绑定到项目且具有固定入口和内容摘要的本机能力。
- Codex 明确建模的内建能力。

运行时不得临时扫描整个用户 Skill 目录并直接加载未锁定内容。用户级能力若要用于项目，必须先建立项目级绑定、来源和摘要。

## 4. 路由请求与决策协议

### 4.1 Route Request

```yaml
schema_version: "1"
request:
  text: 登录接口偶尔返回 500，帮我定位并修复
  operation_intent: modify-project
  explicit_constraints: []
  user_scope: []
project:
  root: /project
  blueprint_digest: sha256:...
  capability_lock_digest: sha256:...
  git_head: ...
  working_tree_digest: sha256:...
task_state:
  task_id: null
  previous_route_id: null
  confirmed_decisions: []
```

### 4.2 Route Decision

```yaml
schema_version: "1"
route_id: route-01J...
task_id: task-01J...
status: ready
classification:
  operation: true
  scenario: bug-fix
  risk: medium
  workflow: systematic
phase:
  current: reproduce
  reroute_on:
    - phase-completed
    - scope-changed
    - risk-increased
    - capability-unavailable
selected:
  skills:
    - capability_id: systematic-debugging
      entrypoint: .agents/skills/systematic-debugging/SKILL.md
      content_digest: sha256:...
      reason: Root-cause investigation is required.
  tools:
    - capability_id: pytest
      executable: .venv/bin/pytest
      reason: Focused reproduction and regression verification.
  mcp_tools: []
deferred:
  - capability_id: code-relationship-analysis
    activate_when: Investigation crosses module boundaries.
rejected: []
permissions:
  already_approved:
    - project.read
    - command.execute
  requires_confirmation: []
context:
  constraints:
    - Do not change authentication behavior before reproducing the failure.
  acceptance:
    - Failure is reproduced.
    - Root cause is demonstrated.
    - Regression test fails before and passes after the fix.
validity:
  project_root: /project
  git_head: ...
  blueprint_digest: sha256:...
  capability_lock_digest: sha256:...
  task_scope_digest: sha256:...
```

### 4.3 接口约束

第一版内部接口可以是：

```bash
vibe route-task --input route-request.json --json
```

未来可替换为结构化 Tool：

```text
project_router.route_task(request) -> RouteDecision
```

无论传输方式如何变化，都必须满足：

- 不启动 Codex。
- 不修改业务代码。
- 不运行项目测试。
- 不隐式安装能力。
- 不在普通路由中访问远程源。
- 输入输出通过版本化 Schema 验证。
- 相同项目状态和请求产生稳定决策。
- 模型可提供语义分类候选，确定性代码必须验证风险和权限下限。

## 5. 能力选择与实际加载

### 5.1 选择顺序

按以下顺序满足能力需求：

```text
Codex 内建能力
→ 仓库已有脚本和依赖
→ 项目级已安装能力
→ 本机已有且已建立项目绑定的可信能力
→ 经用户确认后发现远程候选
```

低权限、本地、确定性方案足够时，不得推荐权限更高的 MCP 或 Plugin。

### 5.2 能力类型

- **Skill：** 当前 Codex 读取固定入口的 `SKILL.md` 并应用其流程。
- **CLI Tool：** 验证可执行入口后，由当前 Codex 直接调用。
- **MCP：** 验证项目授权和连接状态后，仅使用路由选中的工具。
- **Plugin：** 调用其公开的 Skill 或结构化工具。
- **Hook：** 仅在项目策略明确启用时运行。
- **Codex 内建能力：** 直接使用宿主提供的搜索、编辑和命令能力。

### 5.3 加载回执

路由结果包含能力 ID 不等于能力已经使用。当前 Codex 实际加载 Skill 后，必须在任务状态中形成回执：

```yaml
loaded:
  - capability_id: systematic-debugging
    content_digest: sha256:...
    loaded_for_route: route-01J...
```

加载前验证：

- 入口位于允许的项目边界。
- 内容摘要与 Lock 一致。
- Skill 元数据和正文可以解析。
- 依赖工具健康。
- 权限没有扩大。

失败时将能力标记为 unavailable，并重新路由；不得静默使用漂移能力。

## 6. 对话内执行与动态重路由

### 6.1 当前 Codex 执行

Router 只提供结构化目标、范围、阶段、能力和验收条件。当前 Codex 继续在原会话执行，例如 Bug 修复：

```text
reproduce
→ investigate
→ identify-root-cause
→ design-fix
→ implement
→ regression-test
→ full-verification
→ review
```

不得把增强后的任务再次发送给另一个 Codex。

### 6.2 重路由条件

不是每条消息都重新路由。以下事件触发重路由：

- 用户改变目标。
- 用户扩大或缩小范围。
- 工作流阶段完成或切换。
- 新证据提高风险。
- 需要新增权限或外部系统。
- 当前能力不可用或健康检查失败。
- Git HEAD、Blueprint 或 Capability Lock 发生相关变化。
- 用户明确要求重新选择能力。

不影响当前目标、范围、风险和能力状态的普通追问不得导致重复路由。

### 6.3 任务状态

任务状态只保存确认事实和路由状态：

```yaml
task_id: bug-login-500
scenario: bug-fix
current_phase: investigate
route_id: route-01J...
selected_capabilities:
  - systematic-debugging
confirmed_findings:
  - 500 来源于 session repository
user_decisions: []
validity_digest: sha256:...
```

默认不保存完整对话、模型隐藏推理、Secret、生产数据或未确认猜测。

## 7. 能力缺口、推荐和安装

### 7.1 缺口确认

只有依次检查内建能力、仓库能力、项目能力和已绑定本机能力后，仍无法满足需求，才能形成能力缺口。

### 7.2 用户交互

Codex 在当前对话中说明：

- 为什么当前任务需要该能力。
- 不使用会缺失什么验证或保障。
- 推荐候选及排序。
- 来源、维护状态、项目变更、权限和成本。
- 可卸载和回滚方式。

用户可以选择推荐方案、查看详情、替换候选或拒绝安装。

### 7.3 候选安全评估

候选在展示前必须检查：

- 来源和发布者。
- 固定版本、Commit 或内容摘要。
- License 和维护状态。
- 平台、Host 和项目兼容性。
- 安装脚本及文件范围。
- 网络、文件、命令、外部账号和 Secret 风险。
- 已知恶意模式。
- 回滚和卸载能力。
- 是否存在权限更小的替代方案。

热度只用于发现和同等候选排序，不能证明可信。

### 7.4 项目级安装事务

用户同意后：

```text
生成安装预览
→ 确认文件、依赖和权限变化
→ 下载或复制到临时区域
→ 验证来源与摘要
→ 静态安全扫描
→ 原子应用项目变化
→ 验证能力可运行
→ 更新 capabilities.yaml 和 capabilities.lock
→ 重新路由原任务
```

如果首次确认已经包含完整实际变更，不重复确认；实际权限或文件范围扩大时必须重新确认。

默认安装边界：

- `.agents/skills/`
- `.ai-project/providers/`
- 项目依赖文件。
- 项目级 MCP 配置。

默认禁止修改：

- 用户全局 Codex 配置。
- 用户级 Skill 目录。
- 其他项目。
- Shell 全局配置。
- 系统包。

### 7.5 拒绝和反馈

用户拒绝时，Router 把自然语言反馈转换为结构化决策：

```yaml
scope: current-turn | current-task | current-project
action: reject | defer | constrain | replace | unlock
requirement: browser-verification
reason: avoid-large-browser-download
```

随后根据约束重新解析候选或提出明确降级范围。拒绝不能直接终止任务，除非不存在安全可行的替代方案且任务不能在缺少该能力时继续。

### 7.6 安装失败

安装失败必须：

- 回滚已应用变化。
- 不将能力标记为可用。
- 保留脱敏失败原因。
- 提供重试、替换或不用三个方向。
- 保持原任务可恢复。

## 8. 权限和安全

### 8.1 无需额外确认

- 读取项目文件、Git 状态和 Diff。
- 搜索代码。
- 使用已批准且健康的项目级 Skill。
- 运行项目已有的只读检查、测试、Lint 和类型检查。

### 8.2 必须确认一次

- 安装新的项目级能力或依赖。
- 首次启用项目级 MCP。
- 运行会生成项目文件的工具。
- 执行具有明确副作用的命令。
- 使用网络能力。
- 扩大任务操作范围。

### 8.3 每次高风险操作确认

- 访问生产系统或真实用户数据。
- 修改数据库 Schema 或执行数据迁移。
- 部署、发布或回滚。
- 修改认证、支付、安全或 Secret 配置。
- Git 推送、创建 PR、发送消息等外部写入。
- 大量删除或不可逆操作。
- 从项目级扩大到用户全局或系统范围。

已安装工具不能绕过操作级确认。

### 8.4 用户控制

用户可通过自然语言覆盖非强制推荐，例如：

- 这次不要用这个 Skill。
- 换一个更轻量的方案。
- 不要安装 MCP。
- 只分析，不修改。
- 不要联网。
- 这个项目以后都不要推荐它。
- 恢复默认推荐。
- 解释为什么选择它。

用户决策高于推荐，但不能越过组织安全策略。

## 9. 错误处理和恢复

### 9.1 路由内核不可用

- 不得静默假装已路由。
- 不得进入可能产生副作用的项目操作。
- 允许继续普通讨论、只读分析和诊断。
- 用户可选择修复路由环境或明确批准使用 Codex 内建能力降级。

### 9.2 Skill 或工具不可用

```text
标记 unavailable
→ Doctor 诊断
→ 重新解析能力
→ 选择替代候选或形成能力缺口
```

### 9.3 工作区并发变化

如果 Git、工作区、Blueprint、能力锁或权限状态在任务期间变化：

- 停止尚未开始的副作用操作。
- 检查变化是否影响当前路由。
- 相关变化触发重新路由。
- 不相关变化不打断任务。

### 9.4 恢复任务

恢复前检查：

- 原目标与范围是否仍有效。
- Git HEAD 和工作区是否相关变化。
- Blueprint 与 Capability Lock 是否变化。
- 用户确认是否仍覆盖当前权限。

有效时恢复原路由；失效时重新路由，但保留仍然有效的用户决策和确认事实。

## 10. 现有功能迁移

### 10.1 保留并复用

- 仓库事实扫描。
- Skill、CLI、MCP、Plugin 和复合产品盘点。
- Capability Manifest 与能力分类体系。
- Practice Packs。
- 本地能力解析和候选评分。
- 远程发现、安全扫描和来源验证。
- 项目级安装、Lock、卸载和回滚。
- 权限、组织策略、审计和 Doctor。
- Context Capsule 与失效条件。
- 任务场景、风险和工作流模型。
- 结果记录与推荐校准。

### 10.2 重构

- `project-development` 升级为 `project-router`。
- 固定 `_ROUTE_CANDIDATES` 改为动态读取项目能力目录。
- Context Capsule 对外产物改为当前 Codex 可消费的 Route Decision。
- CLI 执行 Checkpoint 改为当前对话的 Route State。
- 能力选择与实际加载之间增加加载回执。
- `AGENTS.md` 增加项目操作路由契约。
- `init` 默认生成完整的对话内路由配置。

### 10.3 降级为内部或诊断接口

- `vibe inspect`
- `vibe init`
- `vibe doctor`
- `vibe route-task`
- `vibe install-project-capability`

用户通常不需要知道这些命令。

### 10.4 退出主链路

- `vibe run` 不再作为正常任务执行入口。
- 当前参数繁重的 `vibe plan` 不再作为用户主入口。
- 通过 CLI 启动第二个 Codex 的任务执行路径进入兼容期并标记 deprecated。

迁移期可保留这些命令用于自动化测试和兼容，但所有用户文档、Bootstrap Skill 和生成项目 Skill 必须以 Codex 对话为唯一正常入口。

## 11. 分阶段交付

### 阶段一：对话内软路由闭环

- 生成 `project-router` Skill。
- 写入 `AGENTS.md` 路由规则。
- 新增只返回决策的 `route-task` 接口。
- 从项目 `capabilities.yaml` 动态构建候选。
- 返回能力入口、原因、权限和失效条件。
- 当前 Codex 加载选中 Skill 并继续任务。
- 禁止启动第二个 Codex。

### 阶段二：能力缺口与安装闭环

- 对话内解释能力缺口。
- 推荐经过验证的项目级候选。
- 用户确认后事务安装。
- 安装成功后自动重新路由。
- 支持拒绝、替换、延后和项目级锁定。
- 安装失败完整回滚。

### 阶段三：任务连续性与动态重路由

- Route State。
- 阶段切换重路由。
- 目标、范围、风险和权限变化检测。
- Skill 加载回执。
- 能力不可用时重新解析。
- 恢复任务时检查路由有效性。

### 阶段四：宿主级硬保障

仅在 Codex 提供稳定 Hook 或 Plugin 接口后实现：

- 编辑文件前检查有效 `route_id`。
- 执行命令前检查权限和路由。
- MCP 工具按 Route Decision 缩减暴露。
- 对遗漏路由进行硬阻止。

宿主级硬保障不是阶段一到三的前置条件，也不能成为延迟对话内软路由上线的理由。

## 12. 测试策略

### 12.1 项目操作识别

覆盖：

- Bug、功能、重构、测试、迁移、审查和发布进入路由。
- 解释、问答和纯讨论不进入路由。
- 讨论转实施时在第一次副作用前路由。
- 同一任务普通追问不重复路由。

### 12.2 动态能力选择

覆盖以下能力目录：

- 只有 Codex 内建能力。
- 存在 `systematic-debugging`。
- 存在多个同类 Skill。
- Skill 已安装但不健康。
- 能力权限超过任务需要。
- 能力被用户拒绝或锁定。

验证：

- Bug 任务优先选择合适调试 Skill。
- 简单任务允许选择零个额外能力。
- 不选择无关能力。
- 候选来自项目清单，不来自固定常量。
- 相同输入产生稳定结果。

### 12.3 当前会话执行

端到端验收必须证明：

- Router 未启动新的 Codex 进程或线程。
- 当前 Codex 实际加载选中 Skill。
- Skill 摘要与 Lock 一致。
- 当前 Codex 随后执行任务。
- 用户无需运行 Vibe 命令。
- 用户从始至终停留在同一对话。

### 12.4 缺口与安装

覆盖：

- 优先复用仓库已有能力。
- 已绑定本机能力优先于远程候选。
- 缺口解释包含必要性、权限和成本。
- 未经确认不能安装。
- 默认只安装到项目。
- 用户拒绝后重新解析。
- 用户反馈形成项目约束。
- 安装失败不留下部分状态。
- 安装成功后重新路由并继续原任务。

### 12.5 权限与风险

覆盖：

- 已批准低风险能力不重复确认。
- 网络、外部写入和权限扩大需要确认。
- 数据库、发布和生产数据每次确认。
- 项目级安装不能写用户全局目录。
- Skill 文本不能绕过确定性权限策略。
- 能力漂移后不能继续加载。

### 12.6 动态重路由

覆盖：

- 阶段变化。
- 目标和范围变化。
- 风险提高。
- 能力失效。
- Git、Blueprint 和 Lock 变化。
- 用户要求替换能力。
- 不相关文件变化不会触发重路由。

### 12.7 对话体验评测

样本集至少包含：

- 30 个应路由的项目任务。
- 30 个不应路由的问答或讨论。
- 20 个讨论中途转实施。
- 20 个任务中途改变范围。
- 20 个能力缺口与用户拒绝。
- 20 个能力安装与重新路由。
- 10 个路由器不可用的安全降级。

指标：

- 项目操作路由召回率。
- 非项目操作误触发率。
- Skill 选择准确率。
- 无关能力选择率。
- 用户无需主动调用 CLI 的成功率。
- 未授权安装率，必须为零。
- 第二 Codex 启动次数，必须为零。
- 路由提示平均长度。
- 安装后原任务继续完成率。

## 13. 发布验收标准

只有同时满足以下条件，才能认为新主链路完成：

1. 用户初始化项目后，只通过 Codex 对话完成后续任务。
2. 用户不需要知道或输入任何 `vibe` 命令。
3. 项目操作在第一次副作用前获得有效路由。
4. 普通问答和讨论不触发路由。
5. Bug 任务能从项目能力目录选择并实际加载调试 Skill。
6. 缺少合适能力时，在当前对话中推荐项目级候选。
7. 用户同意后完成安装、验证、重新路由并继续原任务。
8. 用户拒绝后能够替换、降级或不用。
9. 目标、范围、风险或阶段变化时自动重新路由。
10. 当前 Codex 始终是唯一任务执行者。
11. 正常流程不会启动第二个 Codex 进程或线程。
12. 权限、安装、写入和审计由确定性代码控制。
13. 现有安全、回滚、漂移和组织策略能力不倒退。
14. 真实 Codex 环境完成端到端人工验收，而不仅依赖 Fake 测试。

## 14. 非目标

本设计不要求第一阶段实现：

- 通用多 Agent Runtime。
- 独立聊天 UI。
- 用 Vibe 替代 Codex。
- 自动安装用户全局能力。
- 未经确认访问远程 Registry。
- 保存完整对话或模型隐藏推理。
- 在缺少稳定宿主接口时伪造硬路由保证。

## 15. 最终产品定义

重构后的产品定义为：

> 一个安装到项目中的 Codex 能力路由系统。用户继续正常与 Codex 对话；当请求涉及项目操作时，系统自动识别任务，选择并加载项目级能力，在缺少能力时征得用户同意后完成项目级安装，并由当前 Codex 在原对话中继续执行。

产品不再定义为通过 CLI 启动和治理 Codex 任务的外部编排器。CLI 是项目 Skill 背后的内部确定性控制工具，而不是用户的日常工作界面。
