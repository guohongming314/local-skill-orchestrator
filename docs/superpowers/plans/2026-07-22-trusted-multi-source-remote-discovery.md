# 可信多来源远程能力发现实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 将当前仅加载候选快照的“远程发现”改造成经过用户授权、可查询 MCP Registry、skills.sh、GitHub 和组织 Registry、具备明确状态、硬过滤、可解释排序与独立安装审批的真实发现闭环。

**架构：** 新增独立的发现状态、来源结果和聚合报告模型，由 `DiscoveryService` 调用来源 Adapter，完成规范化、去重、过滤和排序。`vibe init` 只在明确批准后调用发现服务，把候选快照作为缓存输出；Bootstrap Skill 负责对话授权和结果解释，但不自行推断搜索结果。

**技术栈：** Python 3.12、Pydantic、Typer、urllib/httpx 风格只读传输、pytest、现有 RemoteCandidate/Registry/Scoring/Policy/Provenance 组件。

---

## 文件结构

- 新建 `src/vibe/remote/discovery.py`：发现状态、来源诊断、报告和聚合服务。
- 新建 `src/vibe/remote/http.py`：受限只读 JSON/HTML HTTP 传输和错误分类。
- 新建 `src/vibe/remote/sources.py`：MCP Registry、skills.sh、GitHub、组织 Registry Adapter。
- 修改 `src/vibe/remote/models.py`：补充维护度、热度和跨来源身份所需的规范化证据。
- 修改 `src/vibe/remote/scoring.py`：实现五维评分和有界对数热度。
- 修改 `src/vibe/commands/init.py`：真实发现、缓存/离线模式、状态输出和审批边界。
- 修改 `src/vibe/models/resolution.py` 与 `src/vibe/resolver/local.py`：在缺口中携带发现状态和排序候选。
- 修改 `bootstrap-skill/SKILL.md`：要求先批准发现、再批准安装，并区分所有发现状态。
- 修改 `bootstrap-skill/agents/openai.yaml`：保持触发描述与新行为一致。
- 新建或修改 `tests/remote/*`、`tests/commands/test_init_apply.py`、`tests/e2e/test_remote_install_loop.py`、`tests/skills/test_skills.py`：TDD 覆盖。

### 任务一：建立发现状态与聚合报告

- [ ] 在 `tests/remote/test_discovery.py` 写失败测试，覆盖 `not-requested`、`source-unavailable`、`search-failed`、`no-results`、`all-filtered`、`candidates-found` 及部分来源失败。
- [ ] 运行 `uv run pytest tests/remote/test_discovery.py -q`，确认因模型和服务不存在而失败。
- [ ] 在 `src/vibe/remote/discovery.py` 实现 `DiscoveryStatus`、`SourceStatus`、`SourceDiagnostic`、`DiscoveryReport` 和最小聚合逻辑。
- [ ] 运行测试确认通过，并运行 Ruff/MyPy 定向检查。
- [ ] 提交 `feat: model remote discovery outcomes`。

### 任务二：实现只读来源 Adapter

- [ ] 在 `tests/remote/test_sources.py` 写失败测试，使用确定性 Fixture 传输覆盖 MCP Registry、skills.sh、GitHub 和组织 Registry 的分页、限流、认证失败、畸形响应和规范化。
- [ ] 运行测试确认失败原因是 Adapter 尚未实现。
- [ ] 在 `src/vibe/remote/http.py` 实现仅允许 GET、超时、响应大小上限、JSON/文本解析、认证头脱敏和结构化错误。
- [ ] 在 `src/vibe/remote/sources.py` 实现四类 Adapter；GitHub 使用 API 搜索与仓库元数据，skills.sh 解析稳定目录接口或页面元数据，组织 Registry 使用显式配置 URL，MCP 复用 `RegistryClient`。
- [ ] 运行来源测试、Ruff 和 MyPy。
- [ ] 提交 `feat: add trusted remote discovery sources`。

### 任务三：跨来源去重、硬过滤和五维排序

- [ ] 在 `tests/remote/test_discovery.py` 和 `tests/remote/test_scoring.py` 写失败测试，覆盖规范仓库+Commit、包版本+摘要、显式交叉引用去重；名称相同不合并；摘要冲突；热门高风险候选被过滤；低热度高适配候选排名更高；热度对数归一化有上限。
- [ ] 运行测试确认失败。
- [ ] 扩展 `RemoteCandidate`/`CandidateEvidence`，保存规范仓库、Commit、Release、Stars、Forks、采用量、维护时间和跨来源引用。
- [ ] 在 `DiscoveryService` 实现去重和供应链冲突诊断，复用组织策略及安全扫描硬过滤。
- [ ] 在 `scoring.py` 实现适配度 35、可信度 25、风险 20、维护度 10、热度 10 的独立解释分和稳定排序。
- [ ] 运行 Remote 全套测试、Ruff 和 MyPy。
- [ ] 提交 `feat: rank and filter multi-source candidates`。

### 任务四：接入初始化与缓存状态

- [ ] 在 `tests/commands/test_init_apply.py` 写失败测试，证明未授权时零网络请求；授权后执行真实来源搜索；快照缺失不是 `no-results`；缓存模式不联网；来源失败、无结果、全部过滤和找到候选输出不同状态。
- [ ] 在 `tests/e2e/test_remote_install_loop.py` 增加多来源 Fixture，证明 GitHub/skills.sh 去重、部分限流降级、候选排序和独立安装审批。
- [ ] 运行定向测试确认失败。
- [ ] 修改 `vibe init` 参数：保留 `--remote-discovery` 作为发现授权，增加显式 `--remote-offline`/缓存模式和受控来源配置；禁止未授权网络访问。
- [ ] 让初始化从实际能力 Gap 构造查询，调用 `DiscoveryService`，原子写入快照，并将 `DiscoveryReport` 写入 review JSON。
- [ ] 修改 Resolution 模型和 Resolver，使静态候选线索始终保留，远程候选按报告合并，状态不再由空元组推断。
- [ ] 运行命令和 E2E 测试、Ruff、MyPy。
- [ ] 提交 `feat: connect live discovery to initialization`。

### 任务五：更新 Bootstrap Skill 对话治理

- [ ] 在 `tests/skills/test_skills.py` 和 Codex-native E2E 中写失败测试，验证 Skill 必须区分静态线索与远程候选、先请求发现批准、说明来源范围、再请求安装批准、不得把缓存缺失描述为搜索为空。
- [ ] 运行测试确认失败。
- [ ] 修改 `bootstrap-skill/SKILL.md` 和 `agents/openai.yaml`，明确发现状态解释、来源授权、候选排序、部分失败和审批边界。
- [ ] 确保 Skill 仍要求留在当前 Codex 对话，不启动嵌套 Codex。
- [ ] 运行 Skill 与 Codex-native E2E 测试。
- [ ] 提交 `feat: govern conversational remote discovery`。

### 任务六：安全、回归、安装与发布验证

- [ ] 增加候选在审阅与安装间变更导致批准失效的安全测试，并验证日志不包含 Token、Secret 或恶意正文。
- [ ] 运行 `uv run pytest tests/remote tests/commands/test_init_apply.py tests/e2e/test_remote_install_loop.py tests/skills -q`。
- [ ] 运行完整 `uv run pytest -q`。
- [ ] 运行 `uv run ruff check .`、`uv run mypy`、`uv build`、`git diff --check`。
- [ ] 使用 `uv tool install --force .` 更新用户级 `vibe`。
- [ ] 将最新 `bootstrap-skill` 同步至 `~/.codex/skills/bootstrap-skill`，并核对目录内容一致。
- [ ] 运行安装后代码检查和定向回归测试，记录仍需要真实外部凭据或人工 Codex smoke 才能验证的边界。
- [ ] 提交最终测试和文档收口 `test: validate trusted remote discovery`。
