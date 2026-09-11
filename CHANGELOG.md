# 变更记录 (CHANGELOG)

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
