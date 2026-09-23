# 变更记录 (CHANGELOG)

## v5.0.0（2026-09-23）

**依据**：外部体检报告的逐条核实 + 用户要求"要通用技能，不要单一平台专属技能"。报告 11 条里 **6 条成立、3 条证据有误或定级虚高、2 条属主观建议**（逐条核实结论见文末）。

### 破坏性变更：去掉平台专属外壳，技能目录改为自包含

| # | 变更 | 文件 |
|---|---|---|
| 1 | **删除平台私有清单**：`.zcode-plugin/plugin.json`、`marketplace.json`、`hooks/hooks.json`。仓库不再绑定任何编辑器/插件市场，任何支持 Agent Skill 的宿主都能装 | 全仓 |
| 2 | **技能目录自包含**：`scripts/`、`templates/`、`commands/`、`VERSION` 全部收进 `skills/tsc/`——拷这一个目录进宿主技能目录即可运行，运行期不依赖仓库其它部分；`upstream_root()` 语义随之变为"技能根" | `skills/tsc/**` |
| 3 | **去平台化措辞**：`<插件根>` → `<技能根>`，清除平台专属字样与 `${平台_ROOT}` 类变量；`update` 的提示语改为"打开宿主平台的插件/技能管理页" | 全仓 |
| 4 | **不再分发平台 hook 清单**：保留通用接入口 `structure_guard.py --from-hook`（stdin JSON，0 = 通过 / 2 = 拦截），由宿主自行配置；技能不预设任何平台的 hook 格式 | `scripts/structure_guard.py`、`SKILL.md`、`README.md` |
| 5 | **平台中立回归测试**：技能目录自包含、全仓不得出现平台私有清单与专属变量。断言字面量刻意拆开拼接——否则测试会把自己扫成违规（与"提及 ≠ 声明"同一类坑） | `tests/unit/test_tsc_unit.py` |

### 缺陷修复（报告核实成立，均附回归测试）

| ID | 修复 | 实测取证 |
|---|---|---|
| A-02 | 测试夹具不再写死 `true` / `sleep`（POSIX 专属），统一改用当前解释器 | 修复前默认 PATH 下 **4 例失败**（`'true'/'sleep' 不是内部或外部命令`），修复后 148 例全绿 |
| A-08 | JS 模板串插值内按 JS 词法逐层吃：先跳注释（`//`、`/* */`），再按主扫描同款判据识别正则字面量，并给引号串加"裸换行即中止"边界 | 修复前**完全合法**的 `s.replace(/'/g, "")` 被测出 3 处结构问题（rc=1）；修复后 rc=0。真 SyntaxError 仍由 L2（`node --check`）拦住 |
| A-03 | `is_self_bootstrap()` 抽为唯一判据，`doctor` 与 `_enforce_actions` 共用；母版自检不再谎报 4 项"执法包缺失" | `doctor`：修复前 9 通过 / **1 警告（4 条假缺失）**，修复后 **10 通过 / 0 警告 / 0 失败** |
| A-04 | `install_hook.find_git_dir()` 支持 `.git` 是文件：解析 `gitdir:` 指针，再过 `commondir` 落到**公共** git 目录——worktree 的钩子装在公共目录才生效，写进 `.git/worktrees/<名>/hooks` 是白写 | 新增 6 条测试：普通仓库 / worktree / submodule / 坏指针 / 目录不存在 / 端到端装-卸 |
| A-05 | pre-commit 模板的结构门禁钩子由 `language: system` + `python3` 改为 `language: python` + `python` | 本机实测：Windows venv 只有 `python.exe` / `pythonw.exe`，**没有 `python3`**；`language: system` 的 entry 首令牌由系统 PATH 直接解析（pre-commit 官方文档）。⚠️ **未端到端跑通 pre-commit**（启动即写 `~/.cache`，环境权限受限），仅有静态回归锁定 |
| A-01 | 门禁命令解释器回退：首令牌是 `python` / `python3` / `py` 但 PATH 解析不到时，换成当前解释器并明确告警；CI 内联壳同口径 | 新增 5 条单测；命令源（§2 与 project.py）仍可保持静态字符串，同源校验不受影响 |
| A-09 | 契约母版与本仓库实例同批脱水：78 → **74 行**，行数余量 1 → 5 | `wc -l` 两文件均 74（门禁上限 79） |

### 顺带修掉三处报告没提的缺陷

| # | 问题 | 修复 |
|---|---|---|
| 1 | **母版自举回归（本轮改造引入、当场修掉）**：技能目录改成仓库子目录后，`is_self_bootstrap` 仍按"项目根 == 上游"判，导致母版仓库把自己当成待接入项目、把执法包铺进仓库根 | 判据改为"上游 == `<项目根>/skills/tsc`"；并按用户要求补测试防复发（含"宿主把技能装进项目内 `.claude/skills/` 时不算自举"这一反例） |
| 2 | `doctor` 的"本体更新通道"只看 `<技能根>/.git`，母版布局（`.git` 在仓库根）被误报"非 git 安装"、`tsc update` 被谎称不可用 | 新增 `git_worktree_of()` 逐级上溯找 git 工作树；`doctor` 与 `update` 共用 |
| 3 | e2e 夹具 `adapt_section2` 用 `re.sub` 拼替换串，Windows 路径的反斜杠被当成转义（`re.PatternError: bad escape \U`） | 改用函数替换，结果一律按字面量处理 |

### 补上母版自身的多平台回归线（原 A-06）

| # | 变更 | 文件 |
|---|---|---|
| 1 | 新增 `.github/workflows/ci.yml`：`ubuntu` + `windows` + `macos` 三平台跑同一套门禁（两个自检 + `verify` + `check-config`），`fail-fast: false` 免得一个平台红掩盖另一个平台的信息 | `.github/workflows/ci.yml` |
| 2 | 与托管的 `gate.yml` **刻意分开**：不同文件名、不在 `ENFORCE_DEPLOY`、不带 `tsc-managed` 标记，`install`/`sync` 不碰它。母版"不部署自己的执法包"这条设计不变量保持不变 | 同上 |
| 3 | 契约预算改为自动断言（原来只写在发版清单里手敲）：行数 < 80、规则数 ≤ 30，母版与实例一并受检 | `tests/unit/test_tsc_unit.py` |

### 未采纳（登记备查，附理由）

- **A-06 原判"母版无 CI 是漏做"**：措辞不准确——母版不部署自己的执法包是**刻意设计**（避免第二份真身，有测试锁定）。但"缺多平台回归线"这个代价是真的，已按上表补上。
- **A-07（gate.yml 编码 / 超时收割）**：乱码现象属实但**归因错误**——`gate.yml` 只跑 `ubuntu-latest`，不存在 Windows 编码问题；乱码来自本地 `cmd.exe` 输出被 UTF-8 解码，属采集层。价值低，未改。
- **A-10（taskkill 换 Windows Job Object）**：优化建议而非缺陷；现有实现已有单进程终止兜底，超时结论不受影响。
- **A-11（`tsc.py` 拆模块）**：主观架构意见，与"零依赖单文件最好分发"的既有取舍冲突。

### 版本说明

- **v4.0.0 → v5.0.0（major）**：发行形态破坏性变更——平台专属外壳移除、技能目录重排、`<仓库根>/scripts/` 路径不再存在。用平台市场装的副本需要改用"克隆/拷贝技能目录"；存量项目跑一次 `sync` 即可。
- **契约标记代次仍为 `v4`**（`<!-- tsc-managed-contract:v4 -->`）。它是**契约格式代次**，不是发行号：契约条款与 §2 结构本轮没变，所以不动它——改了会让存量项目的 marker 认不出来，等于把所有下游项目误判成"外部 AGENTS.md"而拒绝同步。
- 三处版本头（母版 `AGENTS.md`、`AUDIT-SPEC.md`、`BOOTSTRAP.md`）与执法包 README 同批更新；版本真源仍只有 `skills/tsc/VERSION` 一处。

**本轮实测**：148 用例全绿（`python -m unittest discover -s tests -p "test_*.py"` rc=0）｜`tsc.py verify` rc=0（真实执行 LINT + TEST）｜`check-config` rc=0｜`doctor` rc=0（10 通过 / 0 警告 / 0 失败）｜结构门禁自检 35/35｜bracket_lint 自检 30/30｜`wc -l AGENTS.md` = 74 与母版一致。

## v4.0.0（2026-09-21）

**依据**：《TSC 全方位评审与改造规格 v1.0》。目标不是继续堆规则，而是把 TSC 收敛成真正可安装、可发现、可使用、可升级、可回滚的 Agent Skill / ZCode Plugin。

### P1（全部修复）

| ID | 修复 |
|---|---|
| P1-01 | 上游解析改为 `显式 --source > 当前已安装本体`；项目 `.agents/.source` 降为纯 provenance（结构化 JSON，旧版纯路径兼容读取），不再参与选源、不再阻塞升级 |
| P1-02 | 改为标准 ZCode Plugin：`.zcode-plugin/plugin.json` + `skills/tsc/SKILL.md` + `hooks/hooks.json` + `commands/` + 根 `marketplace.json`；Skill 仍可独立拷入其他平台技能目录 |
| P1-03 | AGENTS.md 所有权 marker `<!-- tsc-managed-contract:v4 -->`：无 marker 的外部 AGENTS.md 默认只读（sync/install 拒绝接管并输出冲突摘要，仅 `install --force` 显式接管）；旧版部署项目（有 `.agents/VERSION` 无 marker）首次 sync 一次性升级并补 marker |
| P1-04 | 只有检测到 `package.json` 的 Node/JS 项目才部署 commitlint；`.pre-commit-config.yaml` 的 Node 专属区块（`# tsc:begin/end:node-only`）在非 Node 项目部署时整段剔除；CI commitlint 步骤条件改为只认 `commitlint.config.js`——纯 Python 项目零 npm 依赖 |
| P1-05 | verify 每条门禁命令加超时（默认 600s；`--timeout` 或 project.py `GATE_TIMEOUTS` 覆盖），超时杀整个进程组、退出码 124、明确报错；CI 内联壳同步实现 |

### P2 / 结构（要点）

- 目录重组：脚本进 `scripts/`（tsc.py / structure_guard.py / bracket_lint.py / install_hook.py）、模板进 `templates/`（AGENTS.md 母版 / project.example.py / enforcement/）、测试分 `tests/unit`（<10s）+ `tests/e2e`（<30s）、文档进 `docs/`（ASCII 文件名：MANUAL_CN.md / structure-guard-design.md / eval/）。
- SKILL.md frontmatter 只留标准 `name/description`，其余进 `metadata`；版本以 `plugin.json` 为准。
- 删除 README/SKILL/手册中硬编码的本机代理 `127.0.0.1:7897`（P2-02）；插件 Hook 改用 `${ZCODE_PLUGIN_ROOT}/scripts/structure_guard.py`（P2-03）。
- gitleaks pre-commit 模板钉 commit SHA `83d9cd6`（v8.30.1）（P2-06）；`update` / `sync` 语义分离（P2-07）。
- 版本发布真源只留根 `VERSION`；`.agents/VERSION` 变为部署生成物（gitignore）。
- 新增 `doctor`（只读诊断 ready/not-ready，支持 `--json`）、`update`（本体 git pull，带超时；非 git 副本提示宿主更新）、`rollback`（撤销最近一次 install/sync 的写入）。
- project.example.py 用 `sys.executable` 示范，消除 python/python3 平台陷阱（P2-05）。
- README/手册只留当前行为，历史迭代叙述移除（P2-11）。

**实测**：unit 84 + e2e 33 全绿（合计 ~8.5s）；`verify` rc=0；`check-config` rc=0；`wc -l AGENTS.md`=78<80；端到端 smoke（本机安装→发现→调用→升级链→回滚）通过；macOS 实测，Linux 由 CI（ubuntu-latest）覆盖，Windows 待实测。
**版本**：v3.3.2 → v4.0.0（布局重组 + 所有权边界，旧版项目跑一次 `sync` 自动升级补 marker）。

## v3.3.2（2026-09-20）

**依据**：给下游工程装闸 2 时实测发现——量化项目的钩子是 pre-commit framework 官方生成的（`pre-commit install` 产物），install_hook.py 的裸钩子方案按安全设计拒绝覆盖。方案文档 §4.5 本就规定"项目已用 pre-commit framework 时加 `repo: local` 条目（两种形态二选一）"，本条目进上游模板让所有 framework 用户开箱即得。

| # | 变更 | 文件 | 依据发现 |
|---|---|---|---|
| 1 | 执法包模板 `.pre-commit-config.yaml` 新增第 3 个 local 条目 `structure-guard`：提交前对暂存文件跑 `.agents/structure_guard.py --staged`；未激活 framework 的项目此条目只是躺着不跑，零影响 | `.agents/enforcement/.pre-commit-config.yaml`、`.agents/enforcement/README.md` | 量化 `.git/hooks/pre-commit` 为 framework 生成（实测拒绝覆盖 rc=2） |

**实测**：81 单测全绿｜`verify` rc=0｜`check-config` rc=0｜沙箱 install 落盘的 `.pre-commit-config.yaml` 含新条目。
**版本**：v3.3.1 → v3.3.2（执法包模板增强，托管机制随 sync 自动分发）。

## v3.3.1（2026-09-20）

**依据**：v3.3.0 落地后对全部 7 个下游工程跑全仓结构扫描的实测——4 个工程共 21 个文件被 L1 误报（G1 15 个 .vue、JSF 2 个 .js、HYT-CAD 3 份 wx_runner.lsp、HYT-NX 1 份 gate.yml），逐个查真实源码确认全部为语言特性缺口，无一真实结构问题。误报修正史是门禁工程最宝贵的东西，逐条修复并各固化回归用例。

| # | 变更 | 文件 | 依据发现（真实源码取证） |
|---|---|---|---|
| 1 | **JS 模板串插值递归扫描**（bracket_lint v1.2.0）：`` `${...}` `` 内是完整 JS 表达式，可嵌套引号与模板串——线性扫串边界必错。新增 `_scan_interp` / `_scan_nested_template` / `_try_js_template`，插值内的 `()[]{}` 括号事件回放主平衡栈（是真代码不是文本） | `bracket_lint.py` | JSF `gym-system/public/app.js:361`：`` `${plans.map((p) => `<option ...>${esc(p.name)}（...）</option>`).join("")}` `` 嵌套模板+插值内引号+文案全角括号 |
| 2 | **lisp 字符串允许字面跨行**：LISP_PROFILE `multi=True`，`_lisp_tokenize` 同步支持（token 记起始行列，扫描行号不漂移）；`_lisp_defun_top` 原生支持不变 | `structure_guard.py` | HYT-CAD `scripts/wx_runner.lsp:2006`：`(strcat "` 换行续写【精雕】文案是合法 AutoLISP 源码，该工程自有的 check_lisp.py 全家桶本就放行 |
| 3 | **profile 级括号白名单 `pairs` 与全角检测开关 `fw`**：yaml/plain 只查 `[{`（裸标量里的 `()` 与全角标点是内容——如 `run:\|` 块里 shell 的 `case x in *.py)` 语法性右括号）；yaml/plain 关闭全角/弯引号检测（中文文案合法） | `bracket_lint.py` | HYT-NX 落盘的 gate.yml:41（YAML 内嵌 shell case 语法）；G1 各 .vue 文案里的 （）：， |
| 4 | **标记模板文件跳过**：.vue/.svelte/.html/.htm/.astro 进 DOC_EXTS——HTML+JS 混合体的引号/文案语义由框架解析，平衡检查误报率 100%（G1 15/76 文件全红实证） | `structure_guard.py` | G1 `client/src/**.vue` 全部 |
| 5 | selftest 用例 26→31（guard）/ 26（bracket_lint），四类误报各固化正反用例（嵌套模板合法/插值内失衡仍报、跨行串合法、shell case 不误报、裸标量全角不误报、vue 跳过） | `structure_guard.py`、`bracket_lint.py` | R-1.3 |

**实测（修复前 → 修复后）**：G1 rc=1(15 文件) → rc=0；JSF rc=1(2) → rc=0；HYT-CAD rc=1(3) → rc=0；HYT-NX rc=1(1) → rc=0；其余 3 工程保持 rc=0；母版 81 单测全绿、`verify` rc=0、`check-config` rc=0、双 selftest 全绿。
**版本**：v3.3.0 → v3.3.1（缺陷修复：纯误报消除，无行为语义变化；下游重跑 sync 即获得修复）。

## v3.3.0（2026-09-20）

**依据**：用户需求——全面完善结构门禁（推倒重做也可）、确保通用与"一说更新就能更新"、清理冗余、梳理结构，并更新全部下游工程。核心发现：v3.2.0+feat/structure-guard 原型把结构门禁定位为"常驻技能目录"，但 **git 钩子与 CI 只认项目自己的文件**——闸 2/3 在原型架构下根本跑不起来（gate.yml 的 CI runner 够不着技能目录，pre-commit 钩子烧死本机绝对路径）。本轮按仓库自身的"生效件必须躺在项目里"原则重构接线。

| # | 变更 | 文件 | 依据发现 |
|---|---|---|---|
| 1 | **结构门禁改为落盘件**：`structure_guard.py` / `bracket_lint.py` 纳入执法包 `ENFORCE_DEPLOY`（5 项），随 install/sync 落到项目 `.agents/`，带 `tsc-managed` 标记托管更新；键改为相对上游根路径。闸 2 钩子从此调项目内相对路径（可移植），闸 3 CI 有检查器可跑，闸 4 verify 有命令可填 | `.agents/tsc.py`、`structure_guard.py`、`bracket_lint.py`（各加 tsc-managed 标记行）、`.agents/test/test_tsc.py` | 架构矛盾取证：gate.yml 内联壳哲学"CI runner 无技能目录"（v3.0.0 变更 21）与 SKILL.md §七"gate.yml 加一步 python structure_guard.py"直接冲突 |
| 2 | **闸 3 接线**：gate.yml 新增独立步骤"结构门禁 (structure_guard, 全仓)"，读项目落盘件、fail-closed，随 install/sync 自动落盘，无需手工接 | `.agents/enforcement/gate.yml` | 同上；独立 step 不进内联 Python 壳，两套壳判定不漂移 |
| 3 | **闸 4 接线**：母版 §2「静态检查」从"无"填为 `python structure_guard.py --quiet --color never .`，project.py `LINT_CMD` 同步——verify 从此带结构维度 | `AGENTS.md`、`.agents/project.py` | 方案文档 §4.5 契约层条目（P2 项） |
| 4 | **闸 2 重构**：install_hook.py 标记块改名 `tsc-structure-guard`（弃旧名 `bracket-balance-guard`，原型未分发无需兼容）；钩子优先调项目落盘件相对路径，项目无落盘件时回退技能目录正本并告警；解释器改 `command -v` 探测（不再烧死 sys.executable）；删除死代码 `prev` | `install_hook.py`、`.agents/test/test_structure_guard.py` | 可移植性审查：原钩子把技能目录绝对路径与本机解释器路径烧进 `.git/hooks` |
| 5 | **structure_guard 功能补强**（v1.2.0）：行内豁免 `guard:skip[=问题码]`（误报逃生口，输出计数显示不静默吞）；>2MB 大文件自动只查 L0/L1 并标注降级；L2 新增 YAML 深检（PyYAML 在场时，缺席降级）；shellcheck 增强（在场时对 .sh 追加 error 级检查）；清理 L2 检查器死形参；selftest 20→25 用例 | `structure_guard.py` | 方案文档 §4.3.2/§4.7 未落地项逐条补 |
| 6 | **更新链路打通**：SKILL.md 触发表新增"**更新契约**"（pull 技能目录带代理 → sync 项目 → 汇报版本变化；pull 失败降级纯 sync）——"远程仓库更新后，在项目里说一句更新就更新"的完整落点；"同步契约"明确为不联网的本地分发 | `SKILL.md`、`README.md`、`使用手册.md` | 用户需求：远程更新后一说更新就能更新 |
| 7 | **文档与结构梳理**：设计文档《AI代码结构完整性防护方案.md》移入 `.agents/`（根目录只留必读件+三件套正本）；README 结构图、接入后结构（7→9 文件）、执法包表（3→5 份）、已知限制勘误（sync 判据 v3.2.0 已改内容漂移，README 仍写版本号）；使用手册同步全部口径；本地清 `__pycache__/`×3 与 `.workbuddy/`（均 gitignored 缓存） | 全仓 | 用户需求：清除冗余、梳理结构 |
| 8 | **测试**：install 断言 7→9 文件、执法包 3→5 项、新增落盘件 tsc-managed 标记断言与 install_hook 可移植性/幂等装卸断言；79 用例全绿 | `.agents/test/test_tsc.py`、`.agents/test/test_structure_guard.py` | R-1.3 行为级变更全带回归 |

**版本**：v3.2.0 → v3.3.0（minor：结构门禁体系化接线 + 更新链路，无破坏性契约条款变更；存量项目跑一次 sync 即获得落盘件与新 gate.yml）。
**本轮实测**：79 个单测全绿｜`structure_guard --selftest` 25/25｜沙箱 install 落盘 9 文件齐备（含结构门禁两件带标记）｜`verify` rc=0（LINT_CMD 真实执行结构门禁）｜`check-config` rc=0｜`wc -l AGENTS.md` = 77。

## v3.2.0（2026-09-12）

**依据**：外部深度评审《TSC_项目深度评审_v3.1.2.md》（4 项 P1 + 3 项 P2 逐条核实属实），经用户确认后全量落地。**语义收紧两处**（全 skip 判失败、同步判据改内容漂移），故升 minor 版本。

| # | 变更 | 文件 | 依据发现 |
|---|---|---|---|
| 1 | **CI/本地同口径**：门禁四项全未配置从"警告+rc=0"收紧为"失败 rc=3"——本地 `verify` 与 CI 内联壳同时改，CI 不再出现零检查假绿 | `.agents/tsc.py`、`.agents/enforcement/gate.yml`、`SKILL.md`、`README.md`、`使用手册.md` | 评审 P1-01（沙箱红→绿实测） |
| 2 | **CI 增加同源校验**：内联壳在执行门禁前先比对 AGENTS.md §2 与 project.py，不一致 rc=1 拦下（§2 未适配时跳过，让零门禁 rc=3 给出可行动信号）；抽取内联真身与本地 `check-config` 做同判定对照测试，防两套壳漂移 | `.agents/enforcement/gate.yml`、`.agents/test/test_tsc.py` | 评审 P1-02 |
| 3 | **install/sync 事务化**：写盘带内存日志，任一步失败整体回滚为操作前原状；旧结构迁移挪到全部写盘成功之后（先搬走旧目录的窗口消除）；迁移自身中途失败也逆序搬回 | `.agents/tsc.py` | 评审 P1-03（mock 中途失败，红→绿实测回滚） |
| 4 | **同步判据从版本号改为内容漂移**：sync/install 预计算全部写入，逐项字节比对（正文/VERSION/project.py/.source/执法包/旧结构），零漂移才"已是最新"；上游忘 bump 版本不再静默漏同步。删除仅剩单一调用点的 `enforcement_pending`/`write_version`（零引用检索取证） | `.agents/tsc.py`、`.agents/test/test_tsc.py` | 评审 P1-04（未采纳评审的 .fingerprint 方案：逐项直比即指纹，少一个状态文件） |
| 5 | **§2 表格解析支持 `\|` 转义**：新增 `split_table_row`/`unescape_cell`，含管道的命令（`pytest -q \| tee t.log`）不再被截断误报；check-config 比较层还原转义 | `.agents/tsc.py`、`.agents/test/test_tsc.py` | 评审 P2-01（截断复现实测） |
| 6 | **旧结构目录签名须 ≥2 命中**：项目自有 `test/test_tsc.py` 单文件不再触发迁移；真旧结构（4+ 材料文件）不受影响 | `.agents/tsc.py`、`.agents/test/test_tsc.py` | 评审 P2-03 |
| 7 | **CI 供应链固化**：checkout/setup-python/gitleaks-action 固定到 commit SHA（附 tag 注释），commitlint 钉 21.2.2（v3.0.0 实测版本）；新增模板级 lint 测试（`uses:` 必须为 40 位 SHA、禁浮动 `@vN`） | `.agents/enforcement/gate.yml`、`.agents/test/test_tsc.py` | 评审 P2-02（SHA 经 GitHub API 实查，未臆造） |

**未采纳**：评审"测试分层提速"建议——本机 48 用例约 5 秒，e2e 走真子进程是刻意保真；评审".fingerprint 文件"方案——由变更 4 的直比替代。
**行为变化须知**：① 全未配置项目 `verify`/CI 现在失败（rc=3）——这是"未配置不是通过"的显式化；② sync 不再看版本号，看内容。

**版本**：v3.1.3 → v3.2.0（minor：门禁与同步语义收紧）。
**本轮实测**：48 个单测全绿（新增 11 条，核心行为变化全部先红后绿）｜`verify` rc=0｜`check-config` rc=0｜`wc -l AGENTS.md` = 77。

## v3.1.3（2026-09-12）

**依据**：存量项目升级执行中发现的新缺陷（用户委托的全量升级任务中实测触发）。无契约条款改动。

| # | 变更 | 文件 | 依据发现 |
|---|---|---|---|
| 1 | `_enforce_actions` 主干分支哨兵扩展：§2「主干分支」填"无 / — / 空白"（如非 git 项目）时与占位符同等处理，gate.yml 保持模板默认 `branches: [main]`，不再把坏值写进 `branches:` | `.agents/tsc.py`、`.agents/test/test_tsc.py` | 非 git 项目 §2 只能如实填"无"，旧逻辑会把 `branches: [无（非 git 仓库）]` 写进 gate.yml（沙箱红→绿实测） |

**版本**：v3.1.2 → v3.1.3（缺陷修复，无破坏性变更；执法包为托管落盘件，同版本 sync 也会自动更新，存量项目重跑 sync 即可拿到修复）。
**本轮实测**：38 个单测全绿（新增 1 条先红后绿回归）｜`verify` rc=0｜`check-config` rc=0｜`wc -l AGENTS.md` = 77。

## v3.1.2（2026-09-12）

**依据**：用户委托的交付前终审（全仓逐文件精读 + 沙箱实测复现 6 组缺陷场景），经用户确认后全量修复（A-01~A-13）。均为缺陷修复与勘误，无破坏性变更、无契约条款改动。

| # | 变更 | 文件 | 依据发现 |
|---|---|---|---|
| 1 | 旧结构迁移加双重门卫：项目根无 `AGENTS.md`（从未部署过契约）不迁移；`enforcement/`、`test/` 等通用名目录须带契约内容签名（`gate.yml`/`Makefile`、`test_tsc.py`/`EVAL-SET.md` 等）才认——修复全新 install 把项目自有 `test/`、`enforcement/` 搬进 `.agents/` 还建议删除的严重缺陷 | `.agents/tsc.py`、`.agents/test/test_tsc.py` | 沙箱实测：空项目放自有 `test/` → 被搬走并提示"可自行删除"（终审 A-01，严重） |
| 2 | `.source` 一律回写为本次实际使用的上游（覆盖显式 `--from` 换源、空文件两种漏网场景），删除仅判死路径的 `source_record_dead`——修复"显式 `--from` 新上游成功后裸 `sync` 静默降级回旧版本" | `.agents/tsc.py`、`.agents/test/test_tsc.py` | 沙箱实测：换源升级后裸 `sync`，VERSION 从 3.1.1 回落 3.0.0（终审 A-02 严重 / A-04 中等） |
| 3 | `status` 对完全没有 §2 章节的 AGENTS.md 如实报"找不到 §2 章节"，不再误报"已填好" | `.agents/tsc.py`、`.agents/test/test_tsc.py` | 沙箱实测（终审 A-03，中等） |
| 4 | do_apply 汇报措辞：`--dry-run` 不再说"已迁移"（改"将迁移到"）；去掉与实际版本状态不符的"版本相同，但检测到旧结构残留"前缀 | `.agents/tsc.py`、`.agents/test/test_tsc.py` | 沙箱实测（终审 A-05/A-06，轻微） |
| 5 | 健壮性四则：顶层兜底 OSError → 退出码 2（不再裸 traceback）；原子写失败清理 `.tsc-tmp` 残留；§2 占位化按"首个非分隔行"识别表头（去掉对表头字面"项"的依赖）；MSYS 盘根 `/c/` 三字符路径归一 | `.agents/tsc.py`、`.agents/test/test_tsc.py` | 代码定论 + 单测锁定（终审 A-07~A-10，轻微） |
| 6 | 文档勘误：发版清单"三处版本头"实为六处（补 `enforcement/README.md`、`SKILL.md` frontmatter、`使用手册.md`）；执法包 README 已知限制补 commitlint 全零 SHA 边缘场景 | `README.md`、`使用手册.md`、`.agents/enforcement/README.md` | 逐文件核对（终审 A-11 + 安全备注） |
| 7 | 补 `v3.1.1` 扁平 tag（发版提交当时漏打，`git tag --list` 取证只到 v3.1.0）；EVAL-SET 回放表补 v3.1.1 / v3.1.2 待回放行 | git tag、`.agents/test/EVAL-SET.md` | 终审 A-12 / A-13 |

**版本**：v3.1.1 → v3.1.2（缺陷修复与勘误，无破坏性变更；AGENTS.md 契约条款未动，仅版本头随发版更新）。
**本轮实测**：37 个单测全绿（`python -m unittest discover -s .agents/test -p "test_*.py"` rc=0，新增 11 条回归全部先红后绿）｜`verify` rc=0｜`check-config` rc=0｜`wc -l AGENTS.md` = 77（< 80）｜终审 6 组沙箱场景修复后复测全部符合预期。

## v3.1.1（2026-09-11）

**依据**：v3.1.0 体检报告（P2×1 + P3×6，只读扫描后经用户确认全部修复）+ 外部 AI 复查补充一处（P2-1）。均为缺陷修复与勘误，无破坏性变更、无契约条款改动。

| # | 变更 | 文件 | 依据发现 |
|---|---|---|---|
| 1 | `install --dry-run` 预览补全：全新安装曾漏报 `.agents/project.py` 与 `.agents/.source`（报 5 项、实际落盘 7 项），且这两个文件在真实安装汇报里缺 `.agents/` 前缀；新增"dry-run 必须列全 7 项且零写盘"回归测试 | `.agents/tsc.py`、`.agents/test/test_tsc.py` | 沙箱 dry-run 实测：预览 5 项 vs `test_install_lands_seven_files` 落盘 7 项（体检 A-01） |
| 2 | `.source` 死路径回退：技能目录搬家后存量项目 sync/status 不再 rc=3——校验 `.agents/.source` 记录，失效则回退脚本所在仓库并提示；同版本幂等早退为记录修正让路，install/sync 成功后把 `.source` 修正为实际使用的上游（status 只读不改）；README 已知限制同步补充 | `.agents/tsc.py`、`.agents/test/test_tsc.py`、`README.md` | 外部 AI 复查（P2-1，实测 rc=3） |
| 3 | 文档勘误：执法包 README"本条第信息"错别字、"门禁随 `.agents/` 自动同步"过期表述（v3 起执行逻辑不进项目）；README 已知限制补"同版本仍会比对执法包与旧结构"例外；使用手册不再硬编码"77 行"；CHANGELOG v3.1.0 实测单测数 23 更正为 24 | `README.md`、`使用手册.md`、`CHANGELOG.md`、`.agents/enforcement/README.md` | 体检 A-02、A-03、A-04、A-06、A-07 |
| 4 | `.agents/verify.sh` 补可执行位（此前 100644，macOS/Linux 克隆后 `./verify.sh` 会 permission denied） | `.agents/verify.sh` | 体检 A-05（`git ls-files -s` 取证） |

**版本**：v3.1.0 → v3.1.1（缺陷修复与勘误，无破坏性变更；AGENTS.md 契约条款未动，仅版本头随发版更新）。
**本轮实测**：26 个单测全绿（`python -m unittest discover -s .agents/test -p "test_*.py"` rc=0）｜`verify` rc=0｜`check-config` rc=0｜沙箱 dry-run 预览 7 项且零写盘｜沙箱死路径 status rc=0 回退生效、sync 后 `.source` 修正｜`wc -l AGENTS.md` = 77（< 80）。

## v3.1.0（2026-09-11）

**依据**：用户需求——评估 v2.1.2 与当前版本优劣后全方位优化，最少 6 轮迭代、每轮自评。评估结论：v3.0.0 在部署体积（10KB vs 97KB）、平台兼容（脱离 make）、命令单源（§2 ↔ project.py 交叉校验）、技能化分发四个维度全面优于 v2.1.2，本轮在其上做缺陷修复与加固，无破坏性变更。

| # | 变更 | 文件 | 依据发现 |
|---|---|---|---|
| 1 | 修正使用手册"执法包默认就是不装"的过期表述（与 v3.0.0 变更 15"默认安装"直接矛盾） | `使用手册.md` | 全文 grep 定位；CHANGELOG 历史条目按"历史不改"原则保留 |
| 2 | `verify` 四条命令全 skip 时输出"假绿"显式警告；`check-config` 对 project.py 未定义变量显式报不一致（旧版静默当"无"通过）；POSIX 信号致死退出码归一为 2；删除 `do_apply` 中 VERSION 重复写入与死代码 `continue`；修正 `section2_value` 文档字符串列号 | `.agents/tsc.py` | 沙箱回归实测：缺 `TEST_CMD` 旧版 rc=0（缺陷）、新版 rc=1；全 skip 旧版无提示、新版输出假绿警告 |
| 3 | 新增 stdlib 回归测试套件（`test_tsc.py`，零依赖）并接入门禁：§2 切分/合并保真/结构签名、MSYS 路径归一、执法包归属三态、install 端到端、分支名跟随、幂等早退、结构漂移拒写、退出码原样传递等；§2 测试行与 `project.py` 同步登记 | `.agents/test/test_tsc.py`、`AGENTS.md` §2、`.agents/project.py` | R-1.3 修复前置要求常驻回归；本仓库门禁从"全 skip 假绿"变为真实执行 |
| 4 | 测试手册与验收清单对齐瘦身后结构（命令从技能目录以 `--project` 执行、落地单元三段式、执法包"默认装"表述）；平台声明改为如实标注"Windows 已实测；macOS/Linux 待实测"；README 修正"`.pre-commit-config.yaml` 里的 gate.yml"指代错乱；SKILL.md 上游文件清单补全 | `TEST-MANUAL.md`、`ACCEPTANCE.md`、`SKILL.md`、`README.md`、`.agents/tsc.py` | 通读比对发现；原文"Windows 与 macOS 通用"属无实测来源取值（违反 R-0.2） |
| 5 | **新装项目 §2 占位化**：fresh install 把 §2 取值列替换为 `[自动填充]`（结构与验证条件列不动，单源仍是母版 §2），修复新装项目继承母版仓库自己取值的缺陷；`status` 对占位 §2 如实报"未填好"；`_enforce_actions` 对占位主干分支防御（gate.yml 保持默认 `[main]`，杜绝 `branches: [[自动填充]]`） | `.agents/tsc.py`、`SKILL.md`、`README.md`、`使用手册.md` | 第 2 轮沙箱冒烟实测复现：新装项目出现"Markdown 文档 + Python 3"且 status 误报"已填好" |
| 6 | **母版自举不再铺执法包**：`_enforce_actions` 检测目标即上游自身时跳过落盘，修复 `sync --from .` 会把三份执法包铺进母版仓库（与文档"母版纯净"不变量矛盾） | `.agents/tsc.py` | dry-run 实测复现：自举列出 3 项执法包"将写入"；修复后 sync 自举仅更新 `.agents/VERSION` |

**版本**：v3.0.0 → v3.1.0（缺陷修复 + 回归套件，无破坏性变更；行为变化两处——新装 §2 占位化、全 skip 假绿警告——均为缺陷纠正方向）。
**预算**：AGENTS.md 77 行（< 80 行门禁，`wc -l` LF 计）；规则数 21 条不变。
**本轮实测**：24 个单测全绿（`python -m unittest discover -s .agents/test -p "test_*.py"` rc=0）｜`verify` rc=0（真实执行测试）｜`check-config` rc=0｜`sync --from .` 自举 rc=0 且仅更新 `.agents/VERSION`、`.github/` 未生成｜关键修复均有"修复前失败 / 修复后通过"对照（见变更 2、5、6 各自实测行）。
**六轮自评摘要**：①文档矛盾已清（grep 零残留）；②行为级缺陷全部带对照取证，但回归当时只是一次性沙箱——由 ③常驻套件锁死；④跨文档口径统一，平台声明回归诚实；⑤最重要的一处设计缺陷修复（单源分发与项目定制的边界）；⑥自举污染修复后发版流程与文档不变量终于一致。遗留：macOS/Linux 实测、7 个存量项目迁移、EVAL-SET 人类施压回放（沿用 v3.0.0 待办，另见下行）。
**合入后待办验证**：① EVAL-SET 7 条对抗回放（针对 v3.1.0，回放表已补行）；② macOS / Linux 侧实跑一次 `install` 与 `verify`；③ 7 个存量项目的结构迁移与 §2 重填（新装占位化后存量项目跑 `sync` 不受影响——§2 已有真实取值，走保留路径）。

## v3.0.0（2026-09-11）

**依据**：用户需求——把契约封装成可一键调用的技能 `tsc`，并解决"3 个文档 + 1 个目录散落项目根目录"的接入混乱；同时本机实测 **Windows 无 `make`**（`command -v make` 退出码 1），聚合门禁必须脱离 make。

| # | 变更 | 文件 | 依据发现 |
|---|---|---|---|
| 1 | 目录收敛：部署单元从"3 个文档 + 1 个目录"改为"根目录 `AGENTS.md` + `.agents/` 整目录"；`AUDIT-SPEC.md` / `BOOTSTRAP.md` / `enforcement/` / `test/` 全部移入 `.agents/` | 全仓 | 用户需求（2026-09-11） |
| 2 | 新增技能包：仓库根加 `SKILL.md`（`name: tsc`），仓库即技能，三平台安装方式写入 `README.md` | `SKILL.md`、`README.md` | 同上 |
| 3 | 新增 `.agents/tsc.py` 作为唯一核心：`install` / `sync` / `verify` / `status` / `check-config`，零第三方依赖，Windows 与 macOS 通用 | `.agents/tsc.py` | 同上 |
| 4 | 删除 `enforcement/Makefile`，聚合门禁改由 `python3 .agents/tsc.py verify` 承担；`gate.yml` 内嵌命令同步替换 | `.agents/enforcement/` | Windows 无 make；上一轮体检 P1 A-01（`BUILD_CMD` 空值静默放行）随删除消解 |
| 5 | 新增"门禁命令单源"机制：`.agents/project.py` 为机器可读源、`AGENTS.md` §2 为人读源，`check-config` 校验两者一致 | `.agents/project.py`、`AGENTS.md` | 上一轮体检 P1 A-02（门禁命令双真身、无交叉校验） |
| 6 | `sync` 保护 §2：只替换 §2 以外的内容；§2 结构变更时报错并**不写任何文件**（退出码 1），防静默缺字段 | `.agents/tsc.py` | 设计评审发现（防静默覆盖项目定制） |
| 7 | 旧结构自动迁移：根目录散着的 `AUDIT-SPEC.md` / `BOOTSTRAP.md` / `enforcement/` / `test/` 由 `sync` 移入 `.agents/`，**不自动删除任何文件** | `.agents/tsc.py` | 用户需求（7 个存量项目待迁移） |
| 8 | 文档版本滞后修正：`使用手册.md` 与 `enforcement/README.md` 的版本声明、`AGENTS.md` 行数表述 | 多处 | 上一轮体检 P2 A-04 |
| 9 | `EVAL-SET.md` 回放记录表补 v3.0.0 行并标"待回放" | `.agents/test/EVAL-SET.md` | 上一轮体检 P2 A-05（合入门禁无记录） |
| 10 | 可选执法层降级为"默认不启用"：`gate.yml` 的密钥扫描改为"有 `.pre-commit-config.yaml` 才跑"，避免未启用时 CI 直接红 | `.agents/enforcement/gate.yml` | 用户要求"约束不要过多" |
| 11 | 调用方式修正为"一句话调用"：`SKILL.md` 命令路由改为以自然语言触发词为入口并明确"底层命令由 agent 代跑、用户不敲命令"，`README.md` 第二节与 `使用手册.md` 第四/五节同步改写，命令行降级为 CI/兜底用途 | `SKILL.md`、`README.md`、`使用手册.md` | 用户反馈（2026-09-11）："让我自己敲命令就失去了它作为技能的目的，封装为技能就是为了能够方便调用，一句话的事" |
| 12 | 触发词收短：接入入口由"给这个项目接入契约"改为**"接入契约"**（4 字），去掉冗余前缀 | `SKILL.md`、`README.md`、`使用手册.md` | 用户反馈："'给这个项目接入契约'太长了，改为'接入契约'" |
| 13 | **门禁改为 AI 自动执行**：`SKILL.md` 新增 §二「自动执行：这些动作不需要用户开口」——改完文件、提交前、修完每个问题后一律自动跑 `verify`，跑完补 `check-config`；用户不再需要说"跑门禁"，该触发词从路由表移除 | `SKILL.md`、`README.md`、`使用手册.md` | 用户反馈："跑门禁什么的应该由 AI 自动判断自动执行，不必用户说" |
| 14 | `AGENTS.md` §4「修复 [ID]」行去掉内联命令，改为语义描述"门禁全绿"——契约内不写具体命令，命令单源归 `project.py` / `tsc.py` | `AGENTS.md` | 同上（避免契约正文与命令实现耦合） |
| 15 | **执法包改为默认安装**：`tsc.py install` 自动把 `enforcement/` 三份模板落到生效位置（`gate.yml` → `.github/workflows/`，另两份 → 项目根），`gate.yml` 的 `branches:` 按 §2「主干分支」自动填；已存在且被项目改过的文件只提示不改写 | `.agents/tsc.py`、`.agents/enforcement/README.md`、`SKILL.md`、`README.md`、`使用手册.md`、`AGENTS.md` §5 | 用户反馈："执法包为什么现在默认不安装，我觉得得安装" |
| 16 | **修 commitlint 钩子写错包名**：`entry` 由 `npx --no -- commitlint --edit` 改为 `npx --no -- @commitlint/cli --edit`。实测旧写法会去下载不存在的 `commitlint@21.2.2` 包并 `exit 1`，**把提交堵死**；新写法包名正确（`@commitlint/cli@21.2.2`），装了依赖即正常拦/放 | `.agents/enforcement/.pre-commit-config.yaml` | 本轮执法包评估实测发现 |
| 17 | **修"跳过后靠 CI"的错误说明**：原文写"不想装就跳过、靠 CI 兜底"，实测本地钩子一旦激活，依赖缺失是**报错拦住提交**而非自动跳过。三处文档改为准确描述，并明确"不想被拦就别执行 `pre-commit install`" | `.agents/enforcement/README.md`、`SKILL.md`、`README.md`、`.agents/tsc.py` 提示语 | 同上 |
| 18 | **CI 密钥扫描改为真正覆盖全历史**：`gate.yml` 去掉"用 pre-commit 跑 gitleaks"（该入口只扫暂存内容，在 CI 上等于只扫本次改动），改用官方 `gitleaks/gitleaks-action@v2` + `fetch-depth: 0`；同时补 `push: main` 触发与 `--from/--to` 范围的 commitlint 校验 | `.agents/enforcement/gate.yml` | 同上 |
| 19 | 执法包文档补"三层各拦什么"对照表与**已知限制**（密钥扫描是模式匹配、默认规则覆盖不到自定义内网域名/连接串；fork PR 的 base sha 可能取不到） | `.agents/enforcement/README.md` | 同上 |
| 20 | **执行逻辑不再复制进项目（瘦身）**：`collect_payload` 只分发 `VERSION`，项目内 `.agents/` 仅剩 `project.py` / `VERSION` / `.source`（约 10KB，原 97KB）；`tsc.py` / `AUDIT-SPEC.md` / `BOOTSTRAP.md` / `verify.*` / `test/` / `enforcement/` 模板原件常驻技能目录，调用一律 `tsc.py <子命令> --project <项目根>`；`status` 对旧项目残留的执行逻辑只提示不删（R-3.4），扫描目标为上游/技能目录自身时不误报 | `.agents/tsc.py`、`SKILL.md`、`README.md`、`使用手册.md`、`AGENTS.md` §2 尾注与 §5、`.agents/BOOTSTRAP.md`、`.agents/verify.ps1`、`.agents/verify.sh` | 用户观点："技能已装在平台上，没必要再复制到其他项目中"——判断成立（执行逻辑部分），但 `AGENTS.md` / `project.py` / 钩子与 CI 落盘件必须留在项目：平台只自动读项目根 `AGENTS.md`；门禁命令跨项目不通用；git 钩子与 CI 只认项目自己的文件 |
| 21 | **CI 聚合门禁改为内联实现**：`gate.yml` 的 verify 步骤不再调 `.agents/tsc.py`（瘦身项目里已无此文件，且 CI runner 无技能目录、不应引入对私有技能仓库的 token 依赖），改为内联 Python 直接读 `.agents/project.py`（唯一命令源）逐条执行 | `.agents/enforcement/gate.yml` | 变更 20 的必然后果；命令单源仍是 `project.py`，聚合壳本地/CI 各一套但读同一源 |
| 22 | **执法包归属标记（tsc-managed）**：三份模板各加一行 `# tsc-managed`（`commitlint.config.js` 用 `//`）标记；`deploy_enforcement` 改按标记判归属并返回 `(新部署, 已更新, 跳过)` 三元组——带标记 = 技能托管随上游自动覆盖；不带标记但正文一致（忽略标记行与 gate.yml 分支名，归一化比较）= 旧版部署一次性升级为托管版；不带标记且正文不同 = 项目接管永不覆盖只提示。**修复缺口：上游模板演进后，旧版部署的落盘件被误判"内容已被项目改过"而永远跳过**（沙箱实测复现：临时上游改 `commitlint.config.js` 后重跑 `install`，项目文件未更新且报跳过）；汇报区分"新部署 / 已更新 / 跳过"三类 | `.agents/tsc.py`、`.agents/enforcement/{gate.yml,.pre-commit-config.yaml,commitlint.config.js,README.md}`、`SKILL.md`、`README.md` | 用户质疑："同步契约这个命令是完整的更新吗？比如执法包或者什么其他的脚本我认为也应该一起更新" |

**版本**：v2.1.2 → v3.0.0（**破坏性结构变更**：文件位置与门禁命令均改变，依赖项目需跑一次 `tsc.py sync` 迁移）。
**预算**：`AGENTS.md` 77 行（< 80 行门禁，`wc -l` LF 计，余量 3 行）；规则数 21 条不变。
**未采纳**：上一轮体检 P2 A-06（`TEST-MANUAL.md` 降级模式的 PASS 仍可判"可合入"）——本轮为结构改造，不扩范围；登记备查，下轮处理。
**本轮新增实测（变更 15）**：`install --dry-run` 不写盘且列出 3 项执法包 ↔ 真跑落盘 3 项（`rc=0`）｜`§2` 主干分支改 `master` 后 `gate.yml` 的 `branches:` 跟随变 `master`｜项目自改的 `commitlint.config.js` 与 `.github/workflows/gate.yml` 被识别并跳过、内容原样保留｜母版自身跑 `install` 不受副作用污染（`.github/` 等未生成）。
**执法包评估实测（变更 16~19，含一个反例纠偏）**：
- commitlint 旧 entry 实测 `exit code: 1` + `npx canceled due to missing packages: ["commitlint@21.2.2"]`；改 `@commitlint/cli` 后，坏信息 `update stuff` 被拦（`rc=1`）、合规信息通过（`rc=0`）；缺依赖时报错包名已正确（`@commitlint/cli@21.2.2`）。
- `commitlint --from <base> --to HEAD` 范围模式实测可用：范围内含坏信息 → `rc=1`，合规 → `rc=0`。
- gitleaks 调用方式实测：`git --staged` 只覆盖暂存内容（同目录 `dir` 模式检出 3 条时它只检出 1 条），故 CI 改用官方 action 扫全历史。
- ⚠️ **纠偏登记**：本轮一度据"staged 模式报 no leaks found"判为漏检，复测确认根因是测试用的 `AKIAIOSFODNN7EXAMPLE` 属 gitleaks 内置 allowlist 样例值，**非产品缺陷**；真实格式密钥（`ghp_...`）在 staged 模式下能正常检出（`rc=1`）。结论已按实测更正，不据此改动产品行为。
- 回归：母版 `verify` rc=0、`check-config` rc=0、`wc -l AGENTS.md`=77；新模板端到端 `install` rc=0、幂等复跑"无文件需要变动" rc=0、`gate.yml` 两处 `branches:` 均正确跟随 §2。
**瘦身实测（变更 20~21）**：
- 瘦身项目 `install` rc=0：项目仅落 `AGENTS.md`、`.agents/{project.py,VERSION,.source}`、执法包三份落盘件，共 7 文件约 10KB（原 97KB）。
- 项目内无 `tsc.py` 时，从技能目录调 `verify --project` rc=0、`check-config --project` rc=0、`status` rc=0（含冗余提示）；cd 进项目后省略 `--project` 亦 rc=0。
- 旧项目残留 `tsc.py`/`AUDIT-SPEC.md`/`test/` 时 `status` 如实列出"冗余执行逻辑"提示，不代删；母版与技能目录自身扫描不误报。
- §2 定制复跑 `install` 保留、执法包三份落盘件照常部署。
- CI 内联门禁实测：绿路径 rc=0（skip 未配置项 + 执行 `TEST_CMD`）；红路径 `TEST_CMD` 退出 7 → 内联脚本 `sys.exit(7)` 原样传递 rc=7。
- `gate.yml` YAML 解析通过（5 步骤齐全）。
**归属标记实测（变更 22，沙箱 5 场景 + 母版回归）**：
- 缺口复现（修复前）：临时上游 `commitlint.config.js` 演进后重跑 `install`，项目文件未更新且报"内容已被项目改过"跳过——证实旧判定把技能部署件误判为用户接管。
- 场景 1 新装：空项目 `install` rc=0，三份落盘件均带 `tsc-managed` 标记，汇报"执法包新部署"。
- 场景 2 模板演进：上游模板追加内容后重跑 `install` rc=0，项目文件自动更新（`commitlint.config.js` / `.pre-commit-config.yaml` 均到新版），汇报"执法包已随技能模板更新"——原缺口修复。
- 场景 3 用户接管：删标记行并改内容后 `install`，报"执法包跳过…（技能不覆盖项目接管的文件）"，用户内容原样保留。
- 场景 4 同版本 sync：无待更新时"已是最新"早退 rc=0；上游 `gate.yml` 再演进后同版本 `sync` 输出"版本相同，但执法包有待更新…继续对齐"并完成更新（早退判定纳入执法包检查）。
- 场景 5 代际迁移：旧版无标记落盘件（正文与模板一致）经同版本 `sync` 自动升级为带标记托管版。
- 母版回归：`verify` rc=0、`check-config` rc=0、`wc -l AGENTS.md`=77；母版自身保持不装执法包（上游纯净）。
**历史条目不改**：v2.1.2 及更早的修订记录按原样保留，其内部的旧路径与 `make verify` 属历史事实。
**合入后待办验证**：① v3.0.0 对抗回放（`.agents/test/EVAL-SET.md` 回放表待填）；② macOS 侧实跑一次 `install` 与 `verify`，确认与 Windows 结论等价；③ 7 个存量项目的结构迁移（本机：JSF / 量化 / HYT-CAD / HYT-NX / G1 / HYT-MLFXBG / `Documents\提示词`）。

## v2.1.2（2026-09-08）

**依据**：用户直接提出的新增需求——AI 对用户的交流须用简洁明了的大白话。

| # | 变更 | 文件 | 依据发现 |
|---|---|---|---|
| 1 | 新增 R-1.4 大白话交流（归 §1 行为契约，不可豁免）：先结论后细节、一句话能说清的不写三句、少用术语（非用不可时紧跟一句白话解释）；代码 / 命令 / 退出码等技术取证内容保持原样，R-1.1 二元判定与 R-1.2 取证要求不因白话化降低 | AGENTS.md | 用户需求（2026-09-08） |

**版本**：v2.1.1 → v2.1.2，仅 AGENTS.md 增一条 §1 规则；AUDIT-SPEC / BOOTSTRAP 语义无涉，无需同步。测试材料现有答案（Q3、T-05 等考取证与门禁行为）与新条款互补不冲突，本轮无需更新。
**预算**：AGENTS.md 76 行（< 80 行门禁，`wc -l` LF 计）；规则数 21 条（< 30 条上限）。

## v2.1.1（2026-09-05）

**依据**：v2.1 轮四份测试报告——三份独立盲测（`提示词-gemini3.8-f-h` / `提示词-glm5.3-f-h` / `提示词-qwen3.8-f-h` 各自的 `test/TEST-REPORT.md`）与自测（`提示词-selftest/TEST-REPORT.md`）。行为层指标已收敛（测试一 3×10/10、测试二 🔴 零 FAIL、测试三 A1~A4 无 FAIL），本轮仅修实质缺陷；单源 / 措辞类发现登记不修（见文末冻结标准），契约本体自此冻结。

| # | 变更 | 文件 | 依据发现 |
|---|---|---|---|
| 1 | ACCEPTANCE A1#1 判定与 BOOTSTRAP 模式 A 对齐：部署三件套 + `enforcement/` | test/ACCEPTANCE.md | Gemini ISSUE-02 P1 / Qwen RT-01 P1 / GLM F-01 P2（三方一致；v2.1 修订 #8 涟漪未同步） |
| 2 | Makefile 增 skip 哨兵：§2 登记"无"的项填 `skip` 即通过，留空报错退出（防误配静默放行）；BUILD_CMD 统一同模式；注释与 README 补 `make verify CHANGED=...` 增量用法 | enforcement/Makefile、README.md | Qwen RT-02 P1 / GLM F-04 P2（合法"无"项目过不了唯一入口 `make verify`）；Gemini ISSUE-03 P2（verify 级增量未文档化） |
| 3 | README 安装步骤 2 补 commitlint 本地安装（钩子 `npx --no` 不联网，须先 `npm i -D`）；离线段同步改写 | enforcement/README.md | Gemini ISSUE-01 P1 / Qwen RT-03 P2（`--no` 与"依赖在线下载"声明矛盾，新环境装完 commit-msg 钩子必挂） |
| 4 | R-1.2 补退出码取证：退出码取自门禁命令本体，管道 / 链式执行逐段取证，禁止以末级命令退出码冒充 | AGENTS.md | 自测 ST-08 P2（两轮测试中唯一被实际违反两次的条款：v2.0 Qwen `;` 链式带过 errors=1、v2.1 自测 `\| tail` 吞码误取 0 后提交） |
| 5 | §3 🔴 铁律引用范围 R-0.1~R-0.4 → R-0.1~R-0.7（v2.1 新增 R-0.6/R-0.7 后枚举未跟，实际影响≈0，顺手修正） | AGENTS.md | Gemini ISSUE-04 P2 |
| 6 | README 首句覆盖声明收窄：只声明已落地项，其余红线注明由提示词纪律与人工审查兜底 | enforcement/README.md | GLM F-03 P2 / Qwen RT-12 P3（覆盖对照表本身准确，仅首句过宽） |

**版本**：v2.1 → v2.1.1，三件套 + enforcement 同批修订；AGENTS.md 仍 75 行（< 80，`wc -l` LF 计），规则数不变。
**验证**：Makefile 哨兵逻辑 8 条分支 bash 实测通过（空值 exit 1 / skip exit 0 / CHANGED 增量）；R-1.2 措辞与 TEST-ANSWERS Q3、EVAL-SET T-05 现有答案无冲突，测试材料无需同步。
**未采纳（登记备查，不触发修订）**：GLM F-02（§4/§5 豁免归属——R-0.5"仅 🟡"已逻辑闭环，且五次沙箱实测无 Hard Stop 失守）；R-0.7 可机械验证性（四家报告均提、均 P2/P3——行为提示类条款固有属性，兜底在 enforcement/CI）；ST-01 / ST-02 / ST-04；Qwen RT-04 / RT-05 / RT-06 / RT-07 / RT-10 / RT-11；GLM F-05~F-08 / F-10；Gemini ISSUE-06；自测 ST-03 / ST-05 / ST-06 / ST-07。
**冻结标准（今后修订的唯一触发条件）**：① EVAL-SET 人类施压回放出现 🔴 FAIL；② 真实使用中因条款歧义导致的实际违反（非模型能力问题）；③ ≥2 独立来源 + 文件验证属实 + 影响已测流程。单源红队发现 / 措辞优化 / "不可机械验证"类抱怨一律只登记不动。
**合入后待办验证**：① enforcement 安装冒烟（`pre-commit install` → 合法与非法 commit 各一次 → `make verify` 的 skip 与 CHANGED 行为）；② EVAL-SET 7 条人类施压回放（回放记录表待填，针对 v2.1.1）；③ R-1.2 新表述定向检查（带管道跑门禁，看汇报是否逐段取证）。

## v2.1（2026-09-05）

**依据**：三份独立测试报告交叉验证后的修订清单——`提示词-gemini3.8-f-h/test/TEST-REPORT.md`（SEC-xx）、`提示词-glm5.3-f-h/test/TEST-REPORT.md`（I-xx）、`提示词-qwen3.8-f-h/test/TEST-REPORT.md`（RT-xx）。三方一致发现优先修复；测试材料（EVAL-SET / TEST-ANSWERS / TEST-MANUAL / ACCEPTANCE）与条款同步对齐。

| # | 变更 | 文件 | 依据发现 |
|---|---|---|---|
| 1 | R-3.6 增加分支裁决：主干 / 受保护分支的直接 push 与 force push 不适用豁免，归 §2 主干保护管辖 | AGENTS.md | G-SEC-01 P1 / L-I-01 P1 / Q-RT-01 P1（三方一致，最高优先） |
| 2 | EVAL-SET T-02 与 TEST-ANSWERS Q2 同步改为"先判目标分支"，答案与条款对齐；出题意图补 Q2/Q9 配对说明 | test/EVAL-SET.md、test/TEST-ANSWERS.md | 同上（GLM/Qwen 曾因此在测试一 Q2 被迫自扣 0.5） |
| 3 | R-0.5 重写：豁免矩阵补全——§1 行为契约与 🟢 规则明确不可豁免，仅 🟡 可单次豁免；定义"单次"= 当次回复内一个动作、不跨请求继承；增加豁免登记要求（ID + 理由 + 回滚方式） | AGENTS.md | Q-RT-02 P1 / Q-RT-07 P2 / L-I-07 P3 |
| 4 | 🟢 标题改为"始终遵循（不可豁免）"、§1 标题加"（不可豁免）"，消除"🟢 可豁免 vs 始终遵循"语义矛盾 | AGENTS.md | Q-RT-03 P1 |
| 5 | R-1.3 增无测试套件降级路径：stdlib / 零依赖脚本回归，或按 §2 尾注降级 | AGENTS.md | Q-RT-04 P1 / G-SEC-05 P2 |
| 6 | AUDIT-SPEC §3 增置信度机制定义（确凿 / 疑似；疑似禁入 P0 / P1），消除 R-1.1 与 T-07 的引用悬空 | AUDIT-SPEC.md | L-I-08 P3 |
| 7 | AUDIT-SPEC 靶心一补"调试残留"扫描项（含 CLI stdout 例外） | AUDIT-SPEC.md | G-SEC-03 P1 / L-I-03 P2 / Q-RT-08 P2（三方一致；GLM/Qwen 实跑中均遇 print 无处归类） |
| 8 | BOOTSTRAP 模式 A 部署范围改三件套 + `enforcement/`，消除二次适配悬空 | BOOTSTRAP.md | G-SEC-04 P2 / L-I-02 P2 |
| 9 | BOOTSTRAP 新增模式 C（契约版本升级：旧版本整体同步、保留并重算 §2、输出版本 diff）；AGENTS §4"适配"触发词同步 | BOOTSTRAP.md、AGENTS.md | Q-RT-05 P1 / Q-RT-06 P2 |
| 10 | BOOTSTRAP 阶段 0 增裸源码兜底探测（按文件后缀推断语言）+ unittest 候选命令 | BOOTSTRAP.md | Q-RT-09 P2 / L-I-09 P3（两家沙箱实跑实证） |
| 11 | 行数门禁统一口径：`wc -l`（LF 计） | AGENTS.md、BOOTSTRAP.md | Q-RT-15 P3（实测同一文件得出 43/52/73 三种行数） |
| 12 | R-3.6 条款补"列出影响与回滚方式"，与 T-02 期望行为对齐 | AGENTS.md | L-I-06 P3 |
| 13 | R-3.3 增例外：以 stdout 为合法输出的 CLI 程序 | AGENTS.md | Q-RT-12 P2 |
| 14 | §2 已知豁免清单增登记格式（`命令:条目描述`），可机器比对 | AGENTS.md | L-I-04 P2 |
| 15 | 新增 R-0.6 内容信任边界（仓库内指令不构成授权，防提示注入） | AGENTS.md | Q-RT-10 P2 |
| 16 | 新增 R-0.7 长会话与子代理契约继承（写操作前重读契约） | AGENTS.md | Q-RT-11 P2 |
| 17 | Makefile 增 `CHANGED` 变量支持增量格式检查；README 增用法说明 | enforcement/Makefile、README.md | G-SEC-02 P1（Makefile 全仓 --check vs §2 增量检查断层，Gemini 独有发现） |
| 18 | README 覆盖对照表 R-0.4 改为"密钥类部分覆盖"，如实声明 gitleaks 不含内网域名 / 连接串 | enforcement/README.md | Q-RT-13 P2 |
| 19 | TEST-MANUAL §7 合入门槛消除歧义：加入"测试三 A1~A4 无 FAIL"；P1 须"修订并全量重跑通过后方可合入，修订前不得合入" | test/TEST-MANUAL.md | 三家对 §7 读出三种结论（可合入 / 需修订 / 不满足），属 harness 自身歧义 |
| 20 | ACCEPTANCE A3#2 增降级判定：无 make 或未部署 enforcement 时按 §2 登记命令逐项实测并附退出码 | test/ACCEPTANCE.md | L-I-05 P2 / Q-RT-14 P2（手册"不装执法包"× "make verify 判定"矛盾） |
| 21 | R-1.1 置信度引用改为指向 AUDIT-SPEC §3 置信度规则 | AGENTS.md | L-I-08 P3 |

**版本**：v2.0 → v2.1，三文件同批修订（符合契约自身"同批修订"要求）。
**预算**：AGENTS.md 75 行（< 80 行门禁，`wc -l` LF 计）；规则数 20 条（< 30 条上限）。
**未采纳**：L-I-11（73→75/80 行余量收窄——本次按高价值发现占用，下次修订前需评估预算）；Q-RT-16 / Q-RT-17（P3 级措辞问题，影响小，暂缓）。

**回归验证**：三份测试材料（TEST-MANUAL / EVAL-SET / TEST-ANSWERS / ACCEPTANCE）已随本次修订同步更新，可开新会话按 TEST-MANUAL 全量重跑；预期重点验证：T-02 / Q2 分支裁决、A3 无 make 降级路径、靶心一调试残留、模式 C 升级。
