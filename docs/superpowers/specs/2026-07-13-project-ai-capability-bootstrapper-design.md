# AI 项目能力初始化器设计

**日期：** 2026-07-13  
**状态：** 已批准进入开发规划  
**仓库：** `local-skill-orchestrator`  
**替代设计：** `2026-07-11-local-skill-orchestrator-design.md`

## 目标

构建一个面向编码 Agent 的本地优先项目初始化与治理系统。

系统分析空白目录或已有仓库，通过对话确认项目目标和用户偏好，盘点本地 Skills、Tools、MCP、Plugins、Hooks 和项目指令，识别能力缺口，并生成项目级开发配置。

当本地能力不足时，后续版本可以发现外部候选，并根据适配度、信任度、风险、维护情况和社区采用情况进行推荐。所有非强制决策都由用户最终控制。

## 产品最终是什么样子

这个项目最终应该是一个可安装的 CLI 加一个全局引导 Skill。

用户进入任意空白目录或已有仓库后执行：

```bash
vibe init
```

系统会完成四件事：

1. 理解用户准备开发什么，以及当前仓库是什么状态。
2. 盘点本机已经安装的开发能力。
3. 根据项目需要选择本地能力，并对缺失能力给出可解释推荐。
4. 生成一套项目级 AI 开发配置，让后续 Codex 知道该怎样开发这个项目。

它不是替代 Codex 的新编码 Agent，也不是单纯的 Skill 市场客户端。它更像是在项目开始前工作的 AI 开发环境架构师。

### 这里所说的“能力”包括什么

这里的能力不仅指纯 `SKILL.md`，也包括 CodeGraph、Claude-Mem 这类复合型产品。

| 例子 | 它提供的核心能力 | 系统中的识别方式 |
|---|---|---|
| `systematic-debugging` | 调试方法和工作流 | Skill |
| `frontend-design` | 前端设计判断和工作流 | Skill |
| `rg`、`git`、`pytest` | 本地确定性执行 | Tool |
| CodeGraph | 代码图、依赖关系、调用关系和结构化代码检索 | 通常是 Tool、MCP 或 Plugin 提供的复合能力 |
| Claude-Mem | 跨会话记忆、历史记录、检索和上下文恢复 | 通常是 Plugin、Hooks、存储服务和检索工具组成的复合能力 |
| GitHub MCP | Issue、Pull Request、Actions 等远程信息和操作 | MCP |
| 一套公司内部开发环境 | Skills、MCP、Hooks 和配置的统一分发 | Plugin |

因此，系统不会要求所有候选都必须是 Skill。它先判断项目需要什么抽象能力，再判断本地哪个产品可以提供这项能力。

例如：

```text
项目需求：理解大型代码库中的调用关系

本地候选：
- CodeGraph：已安装，可以提供结构化代码关系
- rg：已安装，只能进行文本搜索
- repository-exploration Skill：已安装，提供探索工作流

解析结果：
- 将 CodeGraph 绑定为 code-graph-analysis 能力
- 将 rg 绑定为 text-search 能力
- 使用 repository-exploration Skill 规定两者的使用顺序
```

### 复合产品如何处理

CodeGraph、Claude-Mem 这类产品不能简单归类成一个 Skill。系统需要把它们拆成可以理解的能力和权限：

```yaml
provider:
  id: claude-mem
  kind: plugin
  provides:
    - session-memory
    - conversation-search
    - context-recovery
  components:
    - hooks
    - local-storage
    - search-tool
  permissions:
    - project-history.read
    - local-storage.write
```

系统关心的是：

- 它提供哪些能力。
- 通过什么组件提供。
- 是否已经安装并能够运行。
- 会读取和保存什么数据。
- 是否适合当前项目。
- 是否存在权限更小的替代方案。

## 完整使用案例

下面通过一个已有仓库展示用户最终会看到什么。

### 场景

用户有一个刚开始开发的电商后台仓库，本机已经安装：

- CodeGraph。
- Claude-Mem。
- `frontend-design` Skill。
- `systematic-debugging` Skill。
- `git`、`rg`、`node` 和 `pnpm`。
- 没有浏览器测试能力。
- 没有 GitHub MCP。

用户执行：

```bash
cd shop-admin
vibe init
```

### 第一步：仓库分析

系统输出：

```text
检测到已有项目：

- Next.js + TypeScript
- 使用 pnpm
- 存在 PostgreSQL 数据模型
- 已有单元测试，没有端到端测试
- 已配置 ESLint 和 TypeScript 检查
- 没有 AGENTS.md

本地 AI 开发能力：

- CodeGraph：可用
- Claude-Mem：可用
- frontend-design：可用
- systematic-debugging：可用
- 浏览器验证：缺失
```

### 第二步：确认项目目标

系统通过对话询问：

```text
你接下来主要想把这个项目做到什么程度？
```

用户回答：

```text
先完成商品管理和订单管理，之后准备正式上线。
```

系统继续确认无法从仓库判断的高影响问题：

```text
这个后台会操作真实订单和客户数据吗？
是否需要多人协作和 Pull Request 流程？
是否允许我为当前项目安装新的项目级能力？
```

### 第三步：生成能力需求

系统不会立即搜索热门 Skill，而是先生成：

```text
项目需要：

- repository-understanding      必须
- code-graph-analysis          推荐
- frontend-design              必须
- systematic-debugging         推荐
- database-change-review       必须
- browser-verification         必须
- persistent-project-memory    可选
- github-collaboration         可选
- security-review              上线前必须
```

### 第四步：优先绑定本地能力

```text
已使用本地能力：

- repository-understanding
  使用 Codex 内建文件工具、rg 和项目探索工作流

- code-graph-analysis
  使用本地 CodeGraph

- frontend-design
  使用本地 frontend-design Skill

- systematic-debugging
  使用本地 systematic-debugging Skill

- persistent-project-memory
  可以使用 Claude-Mem，但需要保存项目会话历史
```

### 第五步：解释能力缺口

```text
当前缺少：browser-verification

为什么需要：
商品编辑、订单状态修改和权限控制属于关键用户流程，
只运行单元测试无法验证浏览器中的完整行为。

推荐方案：
1. 使用项目已有 Playwright CLI               推荐
2. 安装 Playwright 并配套浏览器测试 Skill     推荐
3. 配置浏览器 MCP                            仅在需要交互式浏览器操作时

系统建议：
优先安装 Playwright CLI，不默认安装浏览器 MCP。
```

这里体现了产品品味：能用低权限、本地、确定性工具解决时，不为了“更 Agentic”而增加 MCP。

### 第六步：用户调整方案

系统展示：

```text
建议配置：

[保留] CodeGraph
[可选] Claude-Mem
[保留] frontend-design
[保留] systematic-debugging
[新增] Playwright CLI
[暂缓] GitHub MCP
[上线前新增] security-review
```

用户可以直接修改：

```text
Claude-Mem 先不要使用；GitHub MCP 也不需要。
Playwright 可以安装。安全审查从现在就加入。
```

系统将这些决定记录为项目级覆盖，而不是下次再次推荐同样内容。

### 第七步：展示 Dry-run

```text
将创建：

- AGENTS.md
- .ai-project/blueprint.yaml
- .ai-project/capabilities.yaml
- .ai-project/capabilities.lock
- .ai-project/policy.yaml
- .ai-project/quality-gates.md
- .agents/skills/project-development/SKILL.md

将修改：

- package.json：增加 test:e2e

将安装：

- @playwright/test，固定版本

不会执行：

- 不配置 Claude-Mem
- 不配置 GitHub MCP
- 不访问生产数据库
- 不修改全局 Codex 配置
```

用户确认后才应用修改。

### 第八步：后续开发体验

初始化完成后，用户正常向 Codex 提出任务：

```text
增加订单退款功能。
```

项目级 Skill 根据已经生成的项目策略判断：

```text
这是一个涉及订单状态、权限和数据库的高风险功能。

使用能力：
1. CodeGraph：分析订单状态和调用关系
2. database-change-review：设计数据变化
3. security-review：检查退款权限和越权风险
4. systematic-debugging：处理实现中的失败
5. browser-verification：验证退款完整流程

工作流：Rigorous
规格 -> 风险检查 -> 实现 -> 测试 -> 独立审查
```

用户仍然可以回答：

```text
这次只是做一个不连接数据库的界面原型，改用 Fast 流程。
```

系统接受调整，并只对当前任务生效。

## 初始化完成后的项目形态

初始化前：

```text
shop-admin/
├── package.json
├── src/
└── tests/
```

初始化后：

```text
shop-admin/
├── AGENTS.md
├── .ai-project/
│   ├── blueprint.yaml
│   ├── capabilities.yaml
│   ├── capabilities.lock
│   ├── policy.yaml
│   ├── decisions.md
│   ├── quality-gates.md
│   ├── workflows.yaml
│   ├── task-policies.yaml
│   └── capability-usage.yaml
├── .agents/
│   └── skills/
│       └── project-development/
│           ├── SKILL.md
│           └── references/
│               ├── capability-routing.md
│               └── quality-gates.md
├── package.json
├── src/
└── tests/
```

其中：

- `AGENTS.md` 告诉 Codex 这个仓库始终要遵守什么。
- `blueprint.yaml` 记录用户想把项目做成什么样。
- `capabilities.yaml` 记录项目需要哪些抽象能力。
- `capabilities.lock` 记录这些能力当前由哪些本地或外部产品提供。
- `policy.yaml` 记录权限和自动化边界。
- `decisions.md` 记录为什么选择或拒绝某些能力。
- 项目级 `SKILL.md` 负责在后续任务中正确组合 CodeGraph、Claude-Mem、其他 Skills、Tools 和 MCP。

因此，这个产品最后交付的不是一个固定开发模板，而是一套针对当前仓库生成、允许用户持续调整的 AI 开发操作说明和能力绑定。

## 完整产品闭环

产品必须同时解决两个不同阶段的问题。

### 阶段一：能力初始化

回答：

```text
这个项目需要哪些开发能力？
本地已经有哪些能力？
缺少哪些能力？
应该选择哪些提供者？
它们需要什么权限？
```

对应命令：

```bash
vibe init
vibe inspect
vibe doctor
```

### 阶段二：任务执行编排

回答：

```text
当前任务属于什么场景？
风险和不确定性有多高？
应该采用什么工作流？
哪些能力在什么阶段使用？
需要哪些验证和审查？
什么时候需要用户确认？
```

这部分主要通过生成的项目级 Skill 自动工作，也可以提供显式命令：

```bash
vibe plan "修复订单退款失败"
vibe explain-task "增加批量导入商品"
```

完整链路是：

```text
项目建模
  -> 能力需求
  -> 能力绑定
  -> 任务分类
  -> 风险分析
  -> 工作流选择
  -> 分阶段调用能力
  -> 验证和审查
  -> 记录结果
  -> 调整未来推荐
```

产品不能只证明“某项能力已安装”，还必须证明“这项能力在正确任务、正确阶段、正确权限下被使用”。

## 意图到执行上下文编译器

产品运行时最核心的职责，不是把所有项目资料、Skills 和工具说明加载进当前窗口，而是动态编译一份完成当前任务所需的最小上下文。

可以将它理解为：

```text
用户原始请求
+ 项目事实
+ 用户和仓库约束
+ 当前可用能力
+ 当前工作区状态
        ↓
意图解析和风险判断
        ↓
工作流与能力选择
        ↓
最小执行上下文 Context Capsule
        ↓
当前 Codex 窗口执行任务
```

### 为什么这样设计

如果把所有 Skills、MCP 工具说明、项目文档和历史记录长期放进上下文，会带来：

- 无关信息占用上下文。
- 多个 Skill 指令冲突。
- Agent 误用不相关工具。
- 历史信息污染当前判断。
- MCP 工具 Schema 长期占用上下文。
- 项目越大，任务执行质量越不稳定。

正确方式是渐进加载：

```text
始终可见：
- 精简项目规则
- 能力名称和简短描述
- 当前任务请求

匹配后加载：
- 选中工作流的必要步骤
- 当前阶段需要的 Skill 正文
- 必要项目引用
- 当前阶段需要的工具

执行中按需加载：
- 相关文件
- CodeGraph 查询结果
- 经过筛选的项目记忆
- MCP 返回的外部数据
```

### Context Capsule

每个任务生成一个短小、结构化、可检查的上下文胶囊：

```yaml
intent:
  type: bug-fix
  goal: 修复订单退款偶发失败

scope:
  modules:
    - orders
    - payments
  prohibited:
    - production-write

acceptance:
  - 能够稳定复现原问题
  - 找到并解释根因
  - 增加回归测试
  - 相关质量检查通过

workflow:
  mode: rigorous
  current_phase: investigate

capabilities:
  selected:
    - systematic-debugging
    - code-graph-analysis
  deferred:
    - browser-verification
  rejected:
    - project-memory

references:
  - .ai-project/quality-gates.md
  - src/orders/
```

Context Capsule 只包含当前阶段需要的信息。进入下一阶段时可以重新编译，而不是不断向同一上下文追加内容。

### 控制面和执行面

系统应拆成两个部分：

```text
控制面 Control Plane
├── 意图解析
├── 项目和风险模型
├── 能力目录
├── 工作流选择
├── 权限策略
└── Context Capsule 编译

执行面 Execution Plane
├── 当前 Codex 窗口
├── 选中的 Skills
├── 当前阶段工具
├── 文件和外部数据
└── 验证执行
```

控制面保存完整配置，但不把完整配置都注入执行面。执行面只接收当前任务的最小必要信息。

### 能力延迟绑定

工具不应在任务开始时全部确定，而应按阶段延迟绑定。

例如新功能开发：

```text
需求阶段
-> 只加载需求澄清和项目目标

架构阶段
-> 加载 CodeGraph、架构规则和相关模块

实现阶段
-> 加载框架 Skill、编辑工具和定向测试

验证阶段
-> 加载 Playwright、质量门禁和审查能力
```

如果任务在需求阶段被取消，就不需要加载或调用后续工具。

### 可以不使用额外能力

编译结果允许选择零个外部 Skill、MCP 或 Plugin。

例如：

```text
任务：修改 README 中的错别字

结果：
- 意图：文档小修改
- 工作流：Fast
- 工具：内建文件编辑
- 外部能力：无
- 验证：Markdown 基础检查
```

“不调用任何额外能力”必须是正常且常见的高质量结果。

### 动态重编译

以下情况触发 Context Capsule 重新编译：

- 用户改变目标或范围。
- 新证据推翻原假设。
- 当前能力不可用。
- 任务风险提高。
- 从调查阶段进入实现阶段。
- 发现需要外部系统或更高权限。
- 验证失败，需要回到调查或设计阶段。

重新编译时保留已确认事实和用户决策，丢弃无关中间信息。

### 上下文限制

“不占用上下文”不能理解成完全零占用。模型至少需要看到：

- 当前目标。
- 当前范围和约束。
- 当前工作流阶段。
- 选中能力的必要使用说明。
- 完成标准。

产品目标应该是最小有效上下文，而不是零上下文。

完整 Skill 内容、工具 Schema、历史记录和大段项目文档应保存在上下文之外，通过路径、能力 ID 和按需查询引用。

### 软路由和硬路由

项目级 Skill 只能实现软路由：告诉 Codex 当前应该加载和使用哪些能力。

如果 Agent Host 已经在会话开始时将全部 MCP 工具定义放入上下文，Skill 无法真正删除这些定义。要实现完整的上下文节省，还需要硬路由层：

```text
软路由
-> 项目 Skill 和 Context Capsule 指导模型选择

硬路由
-> CLI Launcher、Plugin、MCP Gateway 或 Host Adapter
-> 只向会话暴露选中的能力
```

MVP 先实现软路由，并为后续 Host Adapter 保留接口。

### 编译产物必须可失效

Context Capsule 需要记录来源摘要和失效条件。

以下变化必须触发重新编译：

- Git HEAD 或关键工作区文件变化。
- 用户目标、范围和约束变化。
- 项目 Blueprint 或策略变化。
- 能力版本、权限或可用状态变化。
- 工作流阶段变化。

不得继续使用来源已经变化的旧 Capsule。

### 决策边界

LLM 负责：

- 理解意图。
- 识别不确定性。
- 提出能力需求。
- 解释推荐。

确定性程序负责：

- Schema 验证。
- 权限和策略判定。
- 兼容性过滤。
- 版本锁定。
- 文件修改和 Diff。
- 命令执行。
- 安装事务、验证和回滚。

LLM 不得直接绕过确定性策略执行高风险操作。

## 任务执行编排器

### 输入

任务执行编排器读取：

- 用户当前请求。
- 项目 Blueprint。
- 仓库事实和当前 Git 状态。
- 项目风险模型。
- 已绑定能力及可用状态。
- 用户覆盖和团队策略。
- 当前任务允许的操作范围。
- 相似任务的历史结果。

### 输出

任务执行编排器生成：

```yaml
task:
  type: bug-fix
  scope: cross-module
  risk: high
  uncertainty: medium

workflow:
  mode: rigorous
  phases:
    - reproduce
    - investigate
    - identify-root-cause
    - design-fix
    - implement
    - regression-test
    - full-verification
    - review

capabilities:
  investigate:
    - code-graph-analysis
    - text-search
    - project-memory
  regression-test:
    - browser-verification
  review:
    - security-review
```

它不应该只输出一段计划文字，还要形成可执行的阶段图、能力绑定、审批点和完成条件。

### 任务分类维度

任务不能只按“Bug”或“新功能”分类，还需要同时判断：

- 任务类型。
- 影响范围。
- 技术不确定性。
- 业务风险。
- 数据风险。
- 安全风险。
- 是否可逆。
- 是否接近生产环境。
- 是否需要外部系统。
- 是否存在可靠自动验证。

同样是 Bug：

```text
按钮颜色错误
```

和：

```text
重复扣款
```

必须使用完全不同的工作流。

## 内置任务场景

第一版至少支持以下任务场景。每个场景都允许项目 Practice Pack 和用户策略覆盖。

### 1. 缺陷修复

默认流程：

```text
确认现象
-> 稳定复现
-> 收集证据
-> 定位根因
-> 评估影响范围
-> 设计最小修复
-> 增加回归验证
-> 实现
-> 定向测试
-> 完整质量检查
-> 审查
```

能力使用原则：

- CodeGraph 类能力用于跨模块影响分析，不用于替代复现。
- Claude-Mem 类能力只用于恢复相关历史，不把旧结论当成当前事实。
- `systematic-debugging` 用于规定先找根因再修改。
- 测试工具用于先复现、后验证。
- 安全或数据问题增加专门审查。

禁止行为：

- 无法复现时直接猜测修复。
- 只修改报错位置而不确认根因。
- 只运行新增测试，不运行受影响区域验证。
- 因为某个 Skill 已安装就强制调用。

### 2. 新功能开发

默认流程：

```text
确认用户结果
-> 定义验收标准
-> 分析现有架构和复用点
-> 识别风险和数据变化
-> 选择规格强度
-> 设计方案
-> 拆分最小完整切片
-> 实现
-> 自动验证
-> 用户体验检查
-> 审查和文档更新
```

根据功能类型选择能力：

- UI 功能：设计、可访问性、视觉和浏览器验证。
- API 功能：API 设计、契约测试和兼容性检查。
- 数据功能：Schema、迁移、回滚和数据验证。
- AI 功能：Prompt、评测集、回归评测和成本检查。
- 支付和权限：安全、威胁分析和严格审查。

### 3. 代码重构

默认流程：

```text
确认外部行为不变
-> 建立当前验证基线
-> 分析依赖和调用关系
-> 划定重构边界
-> 小批量修改
-> 每批验证
-> 性能和兼容性检查
-> 清理过渡代码
-> 完整审查
```

CodeGraph 类能力在跨模块重构中通常具有较高价值。没有可靠测试基线时，应先补充特征测试或缩小重构范围。

### 4. 性能优化

默认流程：

```text
定义性能目标
-> 建立基线
-> 收集 Profile 和指标
-> 定位瓶颈
-> 提出假设
-> 进行单变量修改
-> 重新测量
-> 检查正确性和资源成本
-> 记录结果
```

禁止仅凭代码外观进行“优化”。没有基线和复测结果时不能声明性能提升。

### 5. 安全修复与安全审查

默认流程：

```text
定义资产和信任边界
-> 识别攻击路径
-> 复现或验证风险
-> 评估数据和权限影响
-> 设计修复
-> 增加负向测试
-> 实现
-> 安全审查
-> 检查日志、Secret 和部署影响
```

涉及凭据、生产数据、认证和授权时自动提高审批等级。

### 6. 数据库 Schema 和迁移

默认流程：

```text
分析当前 Schema 和数据量
-> 定义目标模型
-> 检查兼容性
-> 设计向前迁移
-> 设计回滚或恢复方案
-> 验证锁表和性能风险
-> 在隔离环境测试
-> 应用代码修改
-> 验证读写路径
-> 明确生产执行门禁
```

生产数据库写操作始终需要明确批准。

### 7. 依赖升级

默认流程：

```text
确认升级动机
-> 阅读官方变更和迁移说明
-> 检查兼容范围
-> 固定目标版本
-> 生成最小升级 Diff
-> 运行测试和静态检查
-> 检查供应链和 License 变化
-> 更新 Lockfile 和文档
```

大版本升级和安全升级需要不同策略。不得将整个依赖树无差别升级到最新版。

### 8. 测试补充与质量治理

默认流程：

```text
识别关键行为和失败风险
-> 检查现有测试层次
-> 选择最低成本的有效测试
-> 补充测试
-> 验证测试能够失败
-> 检查稳定性和执行成本
-> 接入质量门禁
```

避免为了覆盖率数字编写没有行为价值的测试。

### 9. UI、UX 和可访问性修改

默认流程：

```text
确认用户任务
-> 检查现有设计系统
-> 设计交互状态
-> 实现
-> 响应式检查
-> 键盘和可访问性检查
-> 视觉验证
-> 浏览器交互验证
```

只有真实用户界面任务才触发设计和视觉相关能力。

### 10. 文档和项目规则更新

默认流程：

```text
确认目标读者
-> 从代码和配置验证事实
-> 修改最接近事实来源的文档
-> 检查命令和链接
-> 避免复制容易漂移的信息
```

稳定项目规则进入 `AGENTS.md`，详细知识进入引用文档，临时任务信息不进入长期规则。

### 11. 发布和部署

默认流程：

```text
确认发布范围
-> 检查工作区和版本
-> 运行完整质量门禁
-> 检查迁移和配置
-> 生成发布说明
-> 验证回滚方案
-> 用户批准
-> 执行发布
-> 发布后健康检查
```

生产发布、付费操作和不可逆修改必须强制人工批准。

### 12. 线上故障处理

默认流程：

```text
确认影响范围
-> 优先止损
-> 保存现场证据
-> 建立时间线
-> 定位根因
-> 设计安全恢复方案
-> 执行经批准的修复
-> 验证恢复
-> 记录复盘和长期改进
```

故障处理中，恢复服务优先于立即进行大型重构。

### 13. 技术探索和可行性验证

默认流程：

```text
明确要回答的问题
-> 定义时间和代码范围
-> 调研候选方案
-> 制作最小实验
-> 记录结果和限制
-> 给出采用或拒绝建议
-> 清理一次性实验代码
```

探索任务不能被误判为生产实现。

### 14. 代码审查

默认流程：

```text
理解变更目标
-> 检查 Diff 和影响范围
-> 验证正确性
-> 检查回归、边界和错误处理
-> 检查安全、性能和可维护性
-> 运行必要验证
-> 按严重程度报告问题
```

审查默认只读，除非用户明确要求同时修复。

## 动态工作流选择

场景模板只是起点。系统根据风险动态增加、删除或替换步骤。

示例：

```text
任务：修改登录按钮文案
场景：UI 修改
风险：低
流程：Fast
能力：文本编辑 + 定向页面检查

任务：增加 OAuth 登录
场景：新功能
风险：高
流程：Rigorous
能力：需求澄清 + 架构分析 + 安全审查
     + 浏览器验证 + 配置检查
```

系统需要避免两种极端：

- 所有任务都走完整重型流程。
- 所有任务都直接修改代码再补验证。

## 能力使用策略

每项能力除了安装信息，还需要定义使用策略：

```yaml
capability:
  id: code-graph-analysis
  provider: codegraph

use_when:
  - repository.size == large
  - task.scope == cross-module
  - task.type in [bug-fix, refactor, architecture-review]

avoid_when:
  - task.scope == single-file
  - index.status != ready

phases:
  - investigate
  - impact-analysis

fallbacks:
  - language-server
  - text-search

verification:
  - referenced-symbols-exist
```

Claude-Mem 类能力的使用策略可以是：

```yaml
capability:
  id: project-memory
  provider: claude-mem

use_when:
  - task.references_previous_decision == true
  - session.context_missing == true

avoid_when:
  - task.can_be_answered_from_repository == true
  - project.policy.memory_disabled == true

rules:
  - 将检索结果视为线索，不视为当前事实
  - 使用仓库内容重新验证历史结论
  - 不保存 Secret 和生产数据
```

这意味着能力目录不能只保存“安装方式”，还要保存：

- 适用条件。
- 不适用条件。
- 建议使用阶段。
- 所需输入。
- 输出和完成标准。
- 权限要求。
- 降级方案。
- 验证方式。
- 与其他能力的先后关系。

## 项目级工作流产物

初始化后增加：

```text
.ai-project/
├── workflows.yaml
├── task-policies.yaml
└── capability-usage.yaml
```

### `workflows.yaml`

保存项目启用的任务场景和阶段模板。

### `task-policies.yaml`

保存风险判断、审批点、Fast/Standard/Rigorous 选择规则和用户覆盖。

### `capability-usage.yaml`

保存每项能力的使用条件、阶段、降级和验证方法。

项目级 `SKILL.md` 读取这些文件，将抽象策略应用到用户的实际任务。

## 任务结果反馈

每次任务结束后可以记录低敏感度结果：

```yaml
outcome:
  task_type: bug-fix
  workflow: standard
  capabilities_used:
    - code-graph-analysis
    - systematic-debugging
  verification_passed: true
  user_rework: false
  unused_recommendations:
    - project-memory
```

后续 `vibe doctor` 可以发现：

- 某项能力安装后从未使用。
- 某个流程持续造成不必要步骤。
- 某类任务经常缺少验证能力。
- 用户重复覆盖相同推荐，应转成项目策略。
- 某项能力经常失败，应更换提供者或降级。

反馈只用于调整项目配置，不应默认上传项目代码、对话内容或敏感数据。

## 产品原则

1. 先建立项目需求模型，再选择具体包。
2. 优先使用内建能力、仓库已有能力和可信本地能力。
3. 只有存在明确能力缺口时才进行外部搜索。
4. 选择最小充分能力集合。
5. 验证和可恢复性优先于代码生成量。
6. 对关键约束使用确定性机制执行。
7. 根据风险调整工作流和审批强度。
8. 将热度作为发现信号，而不是信任保证。
9. 解释推荐理由、权限、成本和替代方案。
10. 保证配置可编辑、可复现、可审计、可升级。

## 用户体验

### 用户不了解候选产品时

初始化对话不得要求用户先了解 CodeGraph、Claude-Mem、MCP 或其他生态产品。

系统应先询问目标和使用场景，再将场景转换成抽象能力需求。只有某项能力适用于当前项目时，才展示具体产品。

错误交互：

```text
是否安装 CodeGraph？
是否启用 Claude-Mem？
```

正确交互：

```text
这个仓库是否需要经常跨多个模块追踪调用关系？
你是否需要在多次会话之间恢复之前的讨论和临时结论？
```

如果用户不了解推荐产品，系统必须使用非产品化语言解释：

- 它解决什么问题。
- 为什么当前项目可能需要。
- 不使用会有什么影响。
- 本地是否已经存在。
- 会读取、保存或发送什么数据。
- 是否有权限更小的替代方案。

用户没有相关需求时直接略过，不展示无关能力市场列表。

### 默认能力分层

#### 基础能力

所有项目默认配置：

- 仓库探索和搜索。
- Git Diff 和恢复方式。
- 构建、运行和测试命令。
- Lint、Format 和 Typecheck。
- 项目规则和完成标准。
- Secret 防护和风险审批。

基础能力优先由内建工具和仓库已有工具提供，不默认安装第三方扩展。

#### 条件能力

满足条件时才推荐：

- 大型或复杂仓库：代码关系分析，可能由 CodeGraph 提供。
- 长期、多会话个人项目：项目连续性记忆，可能由 Claude-Mem 提供。
- 关键 Web 流程：浏览器端到端验证。
- 数据库 Schema 修改：迁移审查。
- 认证、支付和敏感数据：安全审查。

#### 高权限能力

外部账号、完整对话存储、自动 Hooks、浏览器控制、数据库写入和生产部署只能在解释权限后由用户明确批准。

### 初始命令

```bash
vibe init
vibe inspect
vibe explain
vibe doctor
```

未来命令：

```bash
vibe search
vibe diff
vibe reconcile
vibe update
vibe audit
```

### 初始化流程

1. 分析仓库和本地 Agent 环境。
2. 区分已确认事实、推断、未知信息、冲突和缺失能力。
3. 只询问无法从仓库可靠获得的信息。
4. 建立项目模型、风险模型和能力需求集合。
5. 使用本地能力解析项目需求。
6. 输出能力缺口并解释建议的开发策略。
7. 允许用户接受、替换、拒绝、延后或锁定决策。
8. 展示将创建和修改文件的 Dry-run。
9. 生成项目配置，并验证引用和命令。
10. 保存决策、来源、版本和用户覆盖项。

### 推荐信息

每项推荐必须包含：

- 项目需要的能力。
- 建议使用的能力提供者。
- 为什么适用于当前项目。
- 为什么现有本地替代项不足。
- 请求的权限。
- 安装和长期维护成本。
- 可选替代方案和降级行为。
- 推荐强度。

## 领域模型

### 项目模型

```yaml
project:
  lifecycle: blank | existing
  type: web-saas
  phase: prototype | development | beta | production
  stack: {}
constraints: {}
preferences: {}
```

### 开发策略

```yaml
policy:
  default_path: standard
  require_spec_for: []
  require_review_for: []
  verification: []
  production_access: prohibited
```

### 能力需求

能力需求描述项目要达成的结果，不直接绑定具体包。

```yaml
capabilities:
  repository-understanding:
    required: true
  frontend-design:
    required: conditional
  browser-verification:
    required: true
  database-migration-review:
    required: conditional
```

### 能力绑定

```yaml
bindings:
  repository-understanding:
    kind: builtin
  frontend-design:
    kind: local-skill
    provider: frontend-design
  browser-verification:
    kind: tool
    provider: playwright
```

项目工作流引用抽象能力 ID，使用户可以替换具体提供者，而不需要重写项目策略。

## 能力解析

### 解析顺序

1. Agent 内建能力。
2. 仓库已有工具和脚本。
3. 项目级能力。
4. 用户级本地能力。
5. 已配置且可信的 MCP 和 Plugins。
6. 组织批准的能力目录。
7. 官方 Registry 和 Marketplace。
8. 已验证发布者。
9. 社区索引。
10. 普通来源搜索。

### 本地能力验证

选择本地能力前需要验证：

- Agent 和运行时兼容性。
- 所需工具和命令是否存在。
- 是否符合仓库策略。
- 权限范围。
- 版本和来源身份。
- 是否与现有能力重复。
- 是否存在可运行的验证方法。

### 外部候选评估

评分前先应用强制策略过滤。

分别维护：

- `FitScore`：项目和能力适配度。
- `TrustScore`：来源、维护、可审计性和最小权限。
- `RiskScore`：命令执行、凭据、外部写入、提示注入和数据暴露风险。

热度只用于同等级候选之间的排序，不能越过适配度、信任度或项目策略。

## 工作流模式

系统根据任务风险分配工作流，而不是为整个项目强制使用一种模式。

### Fast

用于低风险、局部、容易验证的修改。

```text
分析 -> 修改 -> 定向验证
```

### Standard

用于普通功能和中等规模重构。

```text
澄清 -> 计划 -> 实现 -> 验证 -> 审查
```

### Rigorous

用于安全边界、支付、数据库 Schema、基础设施、破坏性操作和生产发布。

```text
规格 -> 风险审查 -> 设计批准 -> 分阶段实现
-> 完整验证 -> 独立审查 -> 明确集成批准
```

## 生成文件

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

### `AGENTS.md`

只保存稳定且始终适用的信息：

- 项目目标和边界。
- 准确的构建和验证命令。
- 架构和目录约束。
- 依赖修改和生成文件规则。
- 高风险操作策略。
- 任务完成标准。
- 项目级 Skill 的位置。

### 项目级 Skill

只保存按需加载的工作流逻辑：

- 任务分类。
- 风险分类。
- 能力路由。
- Skill 执行顺序。
- Fast、Standard 和 Rigorous 工作流。
- 验证和审查要求。
- 能力缺失时的处理方法。

禁止将第三方 Skill 内容复制进生成的项目 Skill。

### Blueprint 和 Lockfile

`blueprint.yaml` 保存用户可编辑的期望状态。`capabilities.lock` 保存解析出的具体提供者、版本、不可变来源、内容摘要、信任信息和验证状态。

## 实践包

将产品的工程品味维护成版本化 Practice Packs。

每条实践定义：

- 适用条件。
- 推荐强度。
- 所需抽象能力。
- 理由和证据。
- 例外情况。
- 验证方法。

用户可以覆盖推荐。覆盖记录需要保留原始建议、用户理由、作用范围和可选复审条件。

## 权限策略

| 等级 | 描述 | 默认行为 |
|---|---|---|
| L0 | 已有内建能力或只读能力 | 自动使用 |
| L1 | 仅包含 Markdown 的项目级能力 | 一次批准 |
| L2 | 可执行代码、安装包或只读外部访问 | 展示详情后批准 |
| L3 | 凭据、Hooks、外部写入、全局修改或接近生产环境的访问 | 逐项批准 |
| L4 | 来源不可验证、访问无关 Secret 或绕过安全控制 | 阻止 |

任何权限扩大都需要重新批准。

## 文件管理边界

将文件分类为：

- `Owned`：由工具完全管理，可以安全重新生成。
- `Managed`：工具只管理特定节点或标记区块。
- `Observed`：默认只读取，除非用户明确要求修改。

优先使用以下修改方式：

```text
专用 API 或 AST
> JSON/YAML/TOML 结构化修改
> Markdown 标记区块
> 三方合并
> 整文件覆盖
```

## 漂移检测

`vibe doctor` 检查：

- 本地能力缺失或不兼容。
- 命令或运行时不可用。
- MCP 和 Plugin 连接失败。
- 技术栈变化。
- 项目指令与仓库真实状态冲突。
- 能力来源、版本、摘要或权限变化。
- Practice Pack 建议已经弃用。
- 长期未使用、重复或被替代的能力。

将漂移分类为 `expected`、`benign`、`actionable`、`blocking` 或 `security`。不得自动修复用户有意进行的定制。

## MVP 范围

第一版实现：

1. 分析空白目录和已有仓库。
2. 通过对话确认目标、风险、约束和偏好。
3. 盘点本地 Skill、Tool、MCP、Plugin、Hook 和项目指令。
4. 建立项目模型、风险模型和能力需求模型。
5. 使用本地优先策略解析能力。
6. 输出能力缺口。
7. 生成 Blueprint、策略、项目指令、项目级 Skill 和 Lockfile。
8. 生成任务场景、风险策略和能力使用规则。
9. 解释推荐并支持用户覆盖。
10. 使用 `doctor` 验证配置。

第一版不自动安装任何远程能力。

## 未来范围

在验证推荐质量后增加：

- 可信远程能力发现。
- 来源和发布者验证。
- 适配度、信任度、风险和采用情况评分。
- 不可变安装和内容摘要。
- Skill 静态扫描和 MCP 权限扫描。
- Dry-run 和事务式安装。
- 卸载和回滚。
- 漂移协调和版本化迁移。
- 团队和组织策略目录。
- 根据真实开发结果校准推荐。

## 成功标准

- 相同 Blueprint 可以解析出可复现的能力集合。
- 适合的可信本地能力可以被优先复用。
- 只有存在明确能力缺口时才进行外部发现。
- 生成的项目指令保持精简并且针对当前项目。
- 用户可以检查、替换、拒绝、延后和锁定推荐。
- 高风险能力不能在缺少相应批准时启用。
- 工具和能力必须经过验证后才能标记为可用。
- 系统可以检测有意义的项目漂移和能力漂移。
- 系统可以针对不同任务生成与风险匹配的工作流。
- 能力只在适用场景和阶段被调用，并且具有降级方案。
- 缺陷修复、新功能、重构、安全、迁移、发布等核心场景具有可验证的完成标准。
- 评测关注任务结果和返工，而不是安装数量。
