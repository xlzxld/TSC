# TSC 全方位评审与改造规格 v1.0

> 评审对象：用户上传的 `TSC-main.zip`（仓库快照显示版本 v3.3.2）
> 评审目标：把 TSC 从“能工作的契约同步脚本 + Skill 文档”收敛成一个真正可安装、可调用、可升级、可验证的 Agent Skill / ZCode Plugin。
> 说明：本规格针对上传快照；GitHub 上仓库当前 HEAD 未在本轮被可靠抓取，因此不把未核实的远程状态当成事实。

---

## 1. 最终产品定义

TSC 应明确拆成两个层次：

1. **Skill / Plugin 层**：安装在 Agent 平台中，提供自然语言能力、脚本、版本与升级能力。
2. **Project Contract 层**：安装到具体项目，负责 `AGENTS.md`、项目门禁配置、必要的 hook / CI 落盘件。

二者不能混为“仓库根目录既是 Skill 又是项目母版又是 ZCode workspace hook”。

用户最终体验必须做到：

- `安装 TSC`：Agent 从 GitHub 安装。
- `更新 TSC`：Agent 更新已安装的 Skill / Plugin。
- `接入契约`：Agent 将当前版本契约安装到当前项目并自动探测配置。
- `更新契约`：Agent 将当前已安装版本同步到当前项目。
- `升级 TSC 并更新当前项目契约`：一个自然语言请求完成完整升级链。
- `检查 TSC` / `TSC 状态`：返回安装版本、上游版本、项目契约版本、配置状态、hook 状态。
- `TSC 体检`：只读审计。

---

## 2. 当前版本结论

### 2.1 可以保留的基础能力

- `.agents/tsc.py` 已经形成单一同步入口，核心逻辑主要是标准库 Python。
- `install / sync / verify / status / check-config` 的职责已经初步分开。
- 安装 / 同步具备原子写入、journal、失败回滚机制。
- 执法包有 `tsc-managed` 归属标记，设计上支持“托管 / 项目接管 / 新部署”三态。
- `structure_guard.py` / `bracket_lint.py` 的自测目前通过。
- 仓库静态结构检查目前通过。
- 有较完整的回归测试素材。

这些部分不要推倒重写，以修复和收敛为主。

### 2.2 当前不能作为正式发布版本的原因

以下问题至少修完后再把版本标为“可直接安装”。

| ID | 级别 | 问题 | 证据 | 处理要求 |
|---|---|---|---|---|
| P1-01 | P1 | `.agents/.source` 会优先于当前 Skill 目录，导致“更新后裸 sync”仍同步旧版本 | 沙箱实测：旧源 3.3.2 安装后，从新源 3.3.3 运行 `sync --project`，仍报告上游 3.3.2；显式 `--from` 才能更新 | 默认上游必须是“当前已安装 Skill/Plugin”，`.source` 只能作为来源记录，不能压过当前 Skill |
| P1-02 | P1 | ZCode Plugin 结构不完整，没有 `.zcode-plugin/plugin.json`，现有 `.zcode/config.json` 也不是标准插件 Hook 入口 | 当前仓库根无 plugin manifest；ZCode 官方插件结构要求 `.zcode-plugin/plugin.json`，插件 Hook 标准入口是 `hooks/hooks.json` | 改成标准 ZCode Plugin，同时保留可独立安装的 Skill |
| P1-03 | P1 | `sync` 对任意“恰好有同构 §2”的 `AGENTS.md` 缺少明确 TSC 所有权标记；存在误接管项目规范的风险 | `compose_agents_md()` 会用 TSC 母版重建 §2 之外正文；当前主要依赖 §2 结构形状判断，而非 TSC marker | `AGENTS.md` 增加明确管理标记；无 marker 时默认只读检查，不得全文接管；首次接入必须显式确认 |
| P1-04 | P1 | 每个新项目默认部署 commitlint 配置，CI 条件因此几乎恒为真，导致纯 Python 项目也要求 npm/node | install 固定部署 `.pre-commit-config.yaml` + `commitlint.config.js`；gate.yml 检测两文件存在后运行 npm/npx | 只在检测到 Node/JS 项目时启用 commitlint，或改为零 Node 依赖实现；Python-only 项目不能被迫装 npm |
| P1-05 | P1 | `verify` 执行项目自定义命令时没有进程超时，项目命令卡死可导致 Agent 长时间挂死 | `.agents/tsc.py` 使用 `subprocess.run(..., shell=True)`，未设置 timeout | 为每个 gate 增加默认超时、命令级覆盖、超时后杀进程组并返回明确错误 |

---

## 3. 中优先级问题

| ID | 级别 | 问题 | 处理 |
|---|---|---|---|
| P2-01 | P2 | `SKILL.md` frontmatter 放了 ZCode 非标准字段：`agent_created/version/display_name/...` | 保留标准 `name/description`；其它附加信息移入 `metadata`；插件版本以 `plugin.json` 为准 |
| P2-02 | P2 | README/SKILL 硬编码个人代理 `127.0.0.1:7897` | 删除；使用 Git 全局配置、环境变量或 Agent 网络能力；公共仓库绝不绑定作者本机端口 |
| P2-03 | P2 | `.zcode/config.json` 中 Hook 路径为 `${ZCODE_PROJECT_DIR}/structure_guard.py`，实际部署文件在 `.agents/structure_guard.py` | 修正为标准插件 Hook 或明确的 workspace Hook 安装步骤，禁止文档与实际落盘路径分离 |
| P2-04 | P2 | README 声称 macOS/Linux 未实测，却把多平台安装描述得像完整支持 | 发布前至少实测 macOS + Linux；否则文档明确为“未验证平台” |
| P2-05 | P2 | 默认 project.py 模板使用 `python`，但文档又承认 macOS 常用 `python3` | 用 `sys.executable` 或安装时实际探测 Python；不要让命令名成为平台陷阱 |
| P2-06 | P2 | gitleaks pre-commit 模板使用浮动 tag，而 CI 采用 SHA 固定 | pre-commit 模板也固定到 commit SHA，并保留 tag 注释 |
| P2-07 | P2 | “Skill 更新”和“项目契约同步”在自然语言层面仍混为一个动作 | 明确 `update skill`、`sync project`、`upgrade both` 三种操作 |
| P2-08 | P2 | 项目 `.source` 存绝对本机路径，不利于换机器/换 Skill 安装方式 | 改为结构化 provenance：source、ref/version、installed timestamp；本机路径仅作为缓存信息 |
| P2-09 | P2 | 当前 81 条单测存在明显耗时问题；完整套件在本环境 45 秒内无法完成 | 找出慢测，减少重复 subprocess，增加 fast/unit 与 e2e 两层；完整门禁应有可接受上限 |
| P2-10 | P2 | 仓库中版本号有 root `VERSION` 与 `.agents/VERSION` 两份源文件，维护成本高 | 保留一个发布真源；`.agents/VERSION` 只能作为生成物/测试部署件存在 |
| P2-11 | P2 | 文档历史迭代痕迹太多，“自己评审自己的评审”信息量过大 | README/SKILL 只留当前行为；CHANGELOG 保存历史，不把历史决策塞进运行时 Skill |
| P2-12 | P2 | 中文文件名在上传快照中表现为 `#U...` 形式，需确认是否为实际仓库命名 | 若为真实文件名，改为正常 UTF-8 或 ASCII 文件名，避免跨工具编码问题 |

---

## 4. 必须采用的新目录结构

推荐直接转成标准 ZCode Plugin，同时让 Skill 独立可发现：

```text
TSC/
├── .zcode-plugin/
│   └── plugin.json
├── skills/
│   └── tsc/
│       └── SKILL.md
├── commands/
│   ├── tsc.md
│   ├── tsc-update.md
│   ├── tsc-status.md
│   └── tsc-sync.md
├── hooks/
│   └── hooks.json
├── scripts/
│   ├── tsc.py
│   ├── structure_guard.py
│   └── bracket_lint.py
├── templates/
│   ├── AGENTS.md
│   ├── project.example.py
│   └── enforcement/
├── tests/
│   ├── unit/
│   └── e2e/
├── README.md
├── README_CN.md
├── CHANGELOG.md
└── VERSION
```

关键原则：

- `SKILL.md` 负责“何时触发、怎么调用”。
- `commands/` 负责稳定的人类入口。
- `scripts/` 负责实现。
- `templates/` 负责项目落盘模板。
- `hooks/hooks.json` 负责 ZCode 插件 Hook。
- `plugin.json` 负责插件名称、版本、描述、组件声明。
- 不要再让仓库根 `AGENTS.md` 同时充当 Skill 安装入口。

---

## 5. 一句话升级必须这样设计

### 5.1 两种升级对象必须分开

**升级 Skill/Plugin：**

```text
用户：更新 TSC 技能
Agent：检查已安装版本 → 获取最新版 → 校验 → 安装 → 重载 → 验证
```

**更新当前项目契约：**

```text
用户：更新契约
Agent：读取当前已安装 TSC → 对当前项目计算 drift → 安全 sync → check-config → verify
```

**完整升级：**

```text
用户：升级 TSC，并把当前项目一起更新
Agent：升级 Skill/Plugin → 重载 → sync 当前项目 → check-config → verify
```

### 5.2 严格禁止当前的来源优先级

不能继续：

```text
--from > .agents/.source > 当前 Skill
```

必须改为：

```text
显式 source > 当前已安装 Skill/Plugin
```

`.source` 只能作为 provenance，不能决定“当前 Skill 到底是谁”。

---

## 6. AGENTS.md 必须加入所有权边界

推荐加机器标记，例如：

```md
<!-- tsc-managed-contract:v4 -->
```

同步逻辑：

1. 有 marker：允许按 TSC 规则更新 TSC 管理内容。
2. 没 marker：视为外部项目自己的 AGENTS.md，默认不得全文接管。
3. 用户首次说“接入契约”：允许生成/安装 TSC marker。
4. 发现已有 AGENTS.md 且疑似第三方规范：输出冲突摘要，等待用户确认后再做合并。
5. `sync` 永远不因为“§2 长得像”就认定所有权。

这一条是防止最危险的“正常项目被技能母版接管”。

---

## 7. Hook 的正确方案

如果目标是 ZCode：

- 插件级自动 Hook：`hooks/hooks.json`
- 插件根路径使用 `${ZCODE_PLUGIN_ROOT}`
- 项目级 workspace Hook：只有明确需要时才写入项目 `.zcode/config.json`
- 两者不要靠“复制一份然后人工改路径”维持一致。

结构门禁 Hook 应优先走：

```text
hooks/hooks.json
→ ${ZCODE_PLUGIN_ROOT}/scripts/structure_guard.py
```

而不是：

```text
${ZCODE_PROJECT_DIR}/structure_guard.py
```

除非该文件确实由安装器明确落盘到项目根。

---

## 8. CI / pre-commit 规则

### Python-only 项目

不得自动引入 Node 依赖。

### Node/JS 项目

可以启用 commitlint，但依赖状态应由安装器检测并明确报告。

### 多语言项目

由 bootstrap 阶段判断，不能“所有项目统一复制一套门禁”。

### 供应链

- GitHub Actions 使用 40 位 SHA。
- pre-commit 远程仓也尽量使用固定 revision。
- 所有外部安装命令必须有超时和失败提示。

---

## 9. CLI / Agent API 最终契约

底层 CLI 建议稳定成：

```text
tsc install

tsc update

tsc sync

tsc status

tsc doctor

tsc verify

tsc rollback
```

参数：

```text
--project <path>
--source <source>
--version <version>
--dry-run
--force
--timeout <seconds>
--json
```

其中：

- `status`：只读
- `doctor`：只读诊断
- `update`：只更新 Skill/Plugin 本体
- `sync`：只更新项目契约
- `verify`：执行门禁
- `rollback`：恢复上一版本项目契约

Agent 自然语言只是这些动作的上层路由，不应该再依赖长篇 Markdown 自己猜底层命令。

---

## 10. 必须补的自动化测试

至少增加以下回归场景：

### 升级

- 当前 Skill 3.3.2 → 新 Skill 3.3.3：裸 `sync` 必须升级到 3.3.3。
- `.source` 指向旧版本时，新 Skill 仍必须优先使用当前 Skill。
- `.source` 指向无效路径时只作为历史 provenance，不阻塞更新。
- 使用没有 `.git` 的已安装副本时，Skill 仍可通过宿主升级机制获得更新。

### 安全边界

- 无 TSC marker 的 AGENTS.md：`sync` 不得全文覆盖。
- 有 marker 的 AGENTS.md：只更新 TSC 托管区域。
- §2 结构变化：仍然拒绝自动合并。
- 用户接管的执法包：不得被强制覆盖。

### ZCode

- plugin.json 能被验证器接受。
- skill 能被发现。
- hooks/hooks.json 能被加载。
- Hook 路径使用 `${ZCODE_PLUGIN_ROOT}`。
- 插件升级后版本与 Hook 一致。

### 跨平台

- macOS
- Linux
- Windows

至少分别执行 install/status/sync/verify smoke test。

### 性能

- fast unit suite < 10s 目标。
- e2e suite < 30s 目标。
- 任一项目门禁命令超时都不能无限等待。

---

## 11. 发布验收标准

只有同时满足以下条件，才把版本标为正式可安装：

```text
[ ] ZCode plugin.json 合法
[ ] Skill 可发现
[ ] ZCode Hook 自动加载
[ ] GitHub URL 可安装
[ ] 新项目 install 成功
[ ] install 后 doctor 明确报告 ready / not-ready
[ ] 项目配置自动探测正确
[ ] sync 幂等
[ ] 从旧版本升级到新版本成功
[ ] .source 不会阻塞升级
[ ] 无 marker 的外部 AGENTS 不会被接管
[ ] Python-only 项目不会被迫装 Node
[ ] verify 有超时
[ ] rollback 成功
[ ] macOS smoke test
[ ] Linux smoke test
[ ] Windows smoke test
[ ] 全量测试在发布时限内完成
[ ] README 与真实行为完全一致
[ ] VERSION 只有一个发布真源
```

---

## 12. 不要再做的事情

不要继续增加更多“规则”、更多自评轮次、更多历史说明书。

当前 TSC 的主要问题不是“规则不够多”，而是：

```text
安装边界不清
+ 版本边界不清
+ 来源边界不清
+ Hook 边界不清
+ Skill 与项目资产边界不清
```

后续所有修改都优先解决这五件事。

---

## 13. 最终用户体验验收

新机器首次使用：

```text
用户：安装 GitHub 上的 xlzxld/TSC
Agent：完成安装、启用、验证
```

项目首次接入：

```text
用户：接入契约
Agent：探测项目 → 安装 → 配置 → verify → 报告状态
```

版本升级：

```text
用户：更新 TSC
Agent：Skill/Plugin 升级完成
```

项目跟进：

```text
用户：更新契约
Agent：当前项目同步到当前 TSC
```

完整升级：

```text
用户：升级 TSC，并同步当前项目
Agent：升级 Skill/Plugin → 同步项目 → 校验 → 门禁 → 汇报
```

这四个场景必须有端到端 smoke test，不能只靠 README 文字描述。
