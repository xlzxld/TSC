# AI 生成代码结构完整性防护方案（structure-guard）

> 版本 v1.0（设计稿）| 2026-09-19
> 目标：彻底根除 AI 生成代码中的**括号失衡、缩进错乱、结构被破坏**三类问题，以及最阴险的第四类——**"括号总数平衡但结构已经残缺"**。
> 形态：零依赖 Python 校验脚本（核心）+ git 钩子（闸门）+ AI agent hook（首道闸）+ 技能封装（触发入口）。

---

## 0. 结论先行

这个问题的正解**不是再找一个更强的括号检查器**，而是三层认知：

1. **括号失衡是 LLM 的机制性缺陷，不是偶发事故。** 学术研究《Language Models Make Balanced Parentheses Errors》（OpenReview 2025）已证实：模型在长生成中"忘记开着的括号"是内部机制问题，代码量越大越长越高发。HYT-CAD 的坑 #75 更进一步：`(setq` 少一个右括号后 **else 分支被吞进参数表，括号总数仍然平衡**——所有平衡类检查全部漏过，只有真机 `(load)` 才炸。
2. **平衡 ≠ 正确。** 必须按"编码 → 平衡 → 结构 → 形态 → 断言"五层纵深布防，每层拦一类问题（§4.2）。
3. **拦截越早越便宜。** 编辑后立刻查（AI 当场自修，秒级）＞ 提交时查（pre-commit）＞ CI 查（兜底）。第一道闸是给 AI 自己看的——语法工具报错回灌给模型重修的循环已被 NVIDIA RTLFixer 等实践验证有效（§3）。

你手里已有的 11 个工具/脚本，恰好覆盖了这套体系的每个环节，缺的只是**统一编排 + 接到 AI 工作流的闸门**。

---

## 1. 病根诊断：AI 到底怎么把代码写坏

以下每条都有真实事故出处（HYT-CAD `tools/` 各脚本的坑号注释），不是理论推演：

| # | 故障模式 | 真实案例 | 为什么难发现 |
|---|---|---|---|
| 1 | 少闭合括号 | 坑 #75：`(setq` 缺一个 `)` | 编译器只给一句 `unexpected EOF`，不说在哪行开的 |
| 2 | **平衡但残缺** | 坑 #75：else 分支被吞进 setq 参数表，**总数仍平衡** | 一切计数型检查失效；defun 体不被求值，新机加载无恙，换真机才炸 |
| 3 | 结构错位 | 坑 #73：defun 嵌套在别的表达式内，**加载时永不定义** | 字符串搜索"函数存在"，实际是死定义 |
| 4 | 形态残缺 | dt_start v1.0：`(if ...)` 4 段参数，运行时才报"语法错误" | 平衡检查完全无感；只有按调用形态做元数检查才抓得住 |
| 5 | 编码吃字符 | 坑 #64：UTF-8 中文注释被老版 GBK 读法按双字节吞掉，**换行/引号被吃 → 结构物理破坏** | 看源文件完全正常，换个阅读器就坏 |
| 6 | 全角/弯引号混入 | `（）` `【】` `“”` 混进代码 | 中文输入法经典事故；人眼极难分辨 |
| 7 | 缩进错乱 | Python 场景 Tab/空格混用、粘贴错位 | Python 直接语法错误；非缩进敏感语言是慢性可读性毒药 |

**根因**：长上下文生成时注意力稀释（开着的括号记不住）；修补时局部编辑破坏了闭合结构；中英多编码环境混杂。防护体系必须同时覆盖"生成时预防"（做不到，平台不支持约束解码）与"生成后拦截+反馈修复"（成熟可行）。

---

## 2. 现有工具盘点：作用与可借鉴精华

### 2.1 本项目根目录（原型件）

| 文件 | 作用 | 可借鉴的精华 |
|---|---|---|
| `bracket_lint.py` | **语言感知的括号平衡检查器**（14 种语言 profile，单文件零依赖） | ① **profile 机制**：字符串/三引号/模板串/正则字面量/raw string/生命周期全感知，不会把字符串里的括号误判——这是它敢当门禁的底气；② **定位输出三件套**：第一个不平衡点的行:列+插入符、文件尾仍开着的括号栈（每个带行列）、"在末尾按序补上 `} )`"的修复建议——直击"修半天修不好"的真痛点；③ 全角括号/弯引号归一化检测（字符串内合法不误报）；④ `--json` 机器可读输出（给 AI 消费）+ `--selftest` 内置 26 用例自证可信；⑤ 退出码契约 0/1/2；⑥ `--max 5` 截断防刷屏 |
| `install_hook.py` | **pre-commit 钩子安装器**（把 bracket_lint 接到 git 提交） | ① 标记块幂等设计：装/卸只动自己的标记块，绝不碰用户已有钩子内容；② `--force` 覆盖前自动备份 `.bak`；③ worktree/submodule（`.git` 为文件）识别防误装；④ **只拦退出码 1（代码问题），退出码 2（工具自身故障）不误拦**——门禁故障不背代码问题的锅；⑤ 明示 `--no-verify` 逃生口 |

### 2.2 HYT-CAD/tools（实战件，坑里长出来的）

| 文件 | 作用 | 可借鉴的精华 |
|---|---|---|
| `check_lisp.py` | AutoLISP 单文件结构门禁：BOM / 括号平衡 / UNDO 分组 / 关键函数存在性 / 死名残留 / 代码区非 ASCII / if 元数 | ① **min_bal（历史最小深度）+ 首个负深度行**：多闭比少闭更早精确定位；② **"代码视图"与"全文视图"分离**（剥注释后做 token 断言），断言永不被注释里的旧字样误命中；③ 代码区非 ASCII 检查（§1 故障 6 的门禁化）；④ 按文件名切换期望清单（同一门禁服务多脚本） |
| `check_sexpr.py` | **S 表达式语义门禁**：专防"平衡但残缺"（setq 参数奇偶 / if 2~3 段 / foreach ≥3 段） | ① **整个方案的灵魂案例**：坑 #75 证明"平衡检查是必要不充分"，必须再加一层按调用形态的元数检查；② 字节级 tokenizer（GBK 安全：引号/括号不在双字节第二字节范围）；③ 引用糖粘合（`'(1 2 3)` 不误报奇数）——防误报做到语义级 |
| `check_defun_depth.py` | defun 顶层定义检查 | **"行开始时深度必须为 0"这个不变量**：行结束深度 +1 属正常（defun 本来就跨行），开始时 >0 = 嵌套在别的表达式里。一个精心设计的判断消灭一类检查不到的暗雷；含惯用法豁免（`*error*` 局部处理器） |
| `_audit.py` / `_collide.py` | 全库静态审计：同名不同体 / 死代码 / 全局变量泄漏 / 未用参数 / 未定义调用 | ① **函数体规范化哈希比对**抓同名不同体（多脚本同加载互相覆盖，坑 #46）；② `collect_calls` 跳过 defun 参数表与 quote 数据表——**误报修正史全写在注释里**，是门禁工程最宝贵的东西；③ 字符串内符号也计入引用（DCL 宏/回调字符串）防死代码误报 |
| `check_audit_fixes.py` | **历史缺陷回归断言库**：每条断言对应一次真实事故 | ① "事故 → 断言"沉淀模式：修复前失败、修复后通过，永久防止复发（本方案 L4 层的原型）；② `check(cid, desc, fn)` 框架把"加载失败"也报 FAIL 而非吞掉——断言工具自己不许吞异常 |
| `make_ansi.py` | 老版本 AutoCAD 的 GBK 编码副本生成 | 证明**编码差异会物理破坏代码结构**——编码检查是结构防线的一部分（L0 层的存在依据） |
| `check_layer_colors.py` | 图层配色门禁（一致性/唯一性/区分度三断言，CIE Lab 色差） | 关系型约束（跨文件一致、全局唯一、两两可区分）也能形式化为门禁——启发 L4 断言库的表达力 |
| `check_jrt2_out.py` | DXF 产物级回归（零依赖解析 DXF 断言几何） | 静态门禁之外的"产物快照"层思路 |
| `test_direction.py` | 宿主无关算法的 Python 移植回归 | 跑不起宿主（AutoCAD）时，把纯逻辑剥出来测——离线环境门禁的替代路径 |

### 2.3 本项目契约架构（集成骨架，直接复用）

- `SKILL.md` + `.agents/tsc.py`：**执行逻辑常驻技能目录、项目里只落生效件**；退出码 0/1/2/3 全局统一语义；`tsc-managed` 标记决定"技能托管还是项目接管"；`verify` 聚合门禁；**"未配置不是通过（退出 3）"防假绿**。
- `.agents/enforcement/`：本地钩子（扫暂存）/ CI `gate.yml`（全历史）/ 主干保护三层各拦什么，边界写得很清楚。structure-guard 就是往这套三层里**再加一种检查项**，架构零改动。

---

## 3. 业界成熟实践（检索结论）

| 实践 | 核心机制 | 对本方案的输入 |
|---|---|---|
| [tree-sitter](https://tree-sitter.github.io)（Zed/Neovim/Helix 的编辑器内核） | 错误容忍解析：语法坏了不整体失败，而是在语法树里插入 `(ERROR)` / `MISSING` 节点，查询即得精确位置；[增量解析让输入中途也保持可用](https://zed.dev/blog/videogame)（[Zed 博客](https://zed.dev)） | "编辑后立刻红"的产品级实现。作为 L2 深检的**可选增强引擎**（需装 Python 绑定，违反零依赖时自动降级） |
| 《Language Models Make Balanced Parentheses Errors》（[OpenReview 2025](https://openreview.net)） | 实证 LLM 括号失衡是内部机制缺陷 | 证明"必须机器拦截、不能靠提示词自律" |
| [RTLFixer（NVIDIA）](https://github.com/NVlabs/RTLFixer) | 语法工具报错 → 回灌 LLM 修复循环，自动修 LLM 生成的 RTL 语法错误 | **"AI 自修循环"的可行性背书**，本方案闸 1 的理论原型 |
| Hacker News：Lisp 括号问题讨论 | 社区共识：括号敏感语言靠 "syntax-check-and-retry 循环" + 生成后校验 | 同上 |
| [pre-commit framework](https://pre-commit.com) / [lint-staged](https://github.com/lint-staged/lint-staged) / [Prettier 官方方案](https://prettier.io/docs/pre-commit) | 钩子配置化（`.pre-commit-config.yaml`）、**只查暂存文件保速度**、语言无关 | 闸 2 的工程形态；`repo: local` 条目可挂本地零依赖脚本，不用装任何依赖 |

另有一条路线是**约束解码**（grammar-constrained generation，让模型物理上生成不出不平衡括号）——理论根治，但当前主流 agent 平台不开放解码层，落地仍以"生成后校验 + 反馈循环"为准。

---

## 4. 方案总设计

### 4.1 五条设计原则

1. **编译器优先，自研定位兜底。** 有权威语法检查的语言先跑权威检查（`python -m py_compile`、`node --check`、`gofmt -e`…），自研 scanner 只在两种情况上前：权威工具不存在（AutoLISP 等方言）、权威工具只给一句 EOF 不给位置（bracket_lint 的原始定位）。
2. **五层纵深，每层拦一类。** 平衡检查是必要不充分（坑 #75 铁证），必须逐层加码（§4.2）。
3. **拦截越早越便宜。** 闸门按"编辑后 → 暂存时 → 推送前"排列，第一道闸直接对 AI 说话。
4. **事故沉淀为断言。** 每个修掉的结构类 bug 固化为 L4 断言（check_audit_fixes 模式），同款错误永不复发。
5. **零依赖 + 退出码契约 + JSON 输出。** 只用 Python 标准库，任何机器 `python` 一跑就灵；退出码语义全局统一；`--json` 让 AI 能程序化消费报告。

### 4.2 架构：一个核心（五层检测）+ 四道闸（拦截）

```
                    ┌──────────────────────────────────────────┐
                    │        structure_guard.py（统一入口）      │
                    │  编排五层检测 → 汇总报告（文本 + --json）  │
                    └──────────────────────────────────────────┘
   检测层（从便宜到贵，命中即短路）：
   ┌────────────────────────────────────────────────────────────────┐
   │ L0 编码层   BOM / GBK 双字节吞字符 / 全角括号·弯引号 / NUL 二进制 │
   │ L1 平衡层   语言感知括号栈（bracket_lint 现有能力，含 min_bal）   │
   │ L2 结构层   权威语法检查命令表 + （可选）tree-sitter ERROR 节点   │
   │ L3 形态层   调用形态元数/位置不变量（check_sexpr 泛化，插件制）    │
   │ L4 断言层   项目专属历史事故回归断言（check_audit_fixes 泛化）    │
   └────────────────────────────────────────────────────────────────┘
   闸门（从早到晚，全部调同一个入口，只查增量）：
   ┌──────────────┬────────────────────────────────────────────────┐
   │ 闸1 AI编辑后 │ agent hook（PostToolUse: Edit|Write）→ 失败回灌自修│
   │ 闸2 暂存时   │ pre-commit / install_hook.py（只查 git 暂存文件） │
   │ 闸3 推送前   │ CI gate.yml（全仓兜底，fail-closed）              │
   │ 闸4 交付前   │ AGENTS.md §2「静态检查」= structure_guard（verify）│
   └──────────────┴────────────────────────────────────────────────┘
```

### 4.3 实现思路

#### 4.3.1 统一入口与模块划分

```
tools/（或技能目录，执行逻辑不进项目——学 tsc 架构）
├── structure_guard.py    # 入口+编排：收文件列表 → 逐层派发 → 汇总退出码
├── guard_profiles.py     # 语言 profile（bracket_lint 的 PROFILES/EXT_MAP 迁入）+ L3 形态规则表
├── guard_report.py       # 人类可读渲染（插入符定位）+ --json schema
├── bracket_lint.py       # （现有）作为 L0/L1 的实现库 import
└── guard_asserts/        # L4 断言库（每项目一份，check_audit_fixes 模板）
```

#### 4.3.2 L2 结构层：权威检查命令表（compiler-first）

| 语言/格式 | 权威命令 | 说明 |
|---|---|---|
| Python | `python -m py_compile <f>`；失败后 `ast.parse` 取精确行列 | 缩进错乱（TabError/IndentationError）在此层自动被拦——Python 的缩进问题就是语法问题 |
| JavaScript/TypeScript | `node --check <f>`；TS 用 `tsc --noEmit` | js profile 的括号定位器继续兜底 EOF 类报错 |
| Go | `gofmt -e -l <f>` | `-e` 报语法错误 |
| Rust | `cargo check`（有 Cargo.toml 时） | — |
| C/C++ | `gcc -fsyntax-only <f>` | — |
| Shell | `bash -n <f>`；有则加 shellcheck | — |
| Ruby | `ruby -c <f>` | — |
| JSON / TOML | `json.load` / `tomllib`（stdlib） | — |
| YAML | PyYAML 若可用；否则降级 L1 | YAML 缩进即语法，无依赖时只能平衡级 |
| PowerShell | `[System.Management.Automation.Language.Parser]::ParseFile(...)` 取错误行列 | Windows 环境高频，stdlib 即可调 |
| AutoLISP 等方言 | **无权威工具 → 自研**：check_sexpr 的 tokenizer/parser 泛化为 L3 插件 | 这正是自研脚本不可替代的空间 |

执行规则：命令存在才跑（`shutil.which` 探测），不存在**自动降级到下一层**并在报告里标注 `degraded`，绝不因为环境缺工具而假绿。

#### 4.3.3 L3 形态层：插件接口

每语言一张"调用形态规则表"（无此语言对应规则则跳过）：

```python
# guard_profiles.py 中的 L3 规则示例
L3_RULES = {
    "lisp": [
        ArityRule(head="setq",    valid=lambda n: n % 2 == 0, msg="setq 参数须偶数（符号/值成对）"),
        ArityRule(head="if",      valid=lambda n: n in (2, 3), msg="if 只允许 2~3 段"),
        ArityRule(head="foreach", valid=lambda n: n >= 3,     msg="foreach 至少 3 段"),
        TopLevelRule(prefix="(defun", msg="defun 必须定义在顶层"),   # check_defun_depth 泛化
    ],
    # python: 编译器已覆盖绝大多数形态，仅在需要时加项目专属规则
}
```

实现上就是对 L2 产出的 AST（或自研轻量 parser，LISP 家族用 check_sexpr 的现成件）做一次 walk。**规则必须来自真实事故**——每条规则注释里写坑号/出处，防止规则表膨胀成猜想集合。

#### 4.3.4 L4 断言层：事故沉淀模板

直接复制 `check_audit_fixes.py` 的框架：`check(cid, desc, fn)` 三元组 + 全局 RESULTS + 汇总退出码。铁律两条：断言函数内部异常必须报 FAIL 而不是崩掉整个门禁（原文件已这么做）；每条断言的注释必须写清"哪次事故、什么症状"。新项目接入时初始为空库，每次修结构类 bug 后由 AI 按 R-1.3 追加一条。

#### 4.3.5 报告契约

退出码（全局统一，对齐 tsc.py 语义）：

| 码 | 含义 | 闸1/闸2 行为 | 闸3 行为 |
|---|---|---|---|
| 0 | 全部通过 | 放行 | 放行 |
| 1 | **代码结构问题** | 拦截，报告回灌 AI / 阻止提交 | CI 失败 |
| 2 | **工具自身故障**（权威命令缺失且无法降级、IO 崩溃） | **告警放行**（不背误拦的锅），人类看到显著警告 | CI 失败（fail-closed 兜底在此收口） |
| 3 | 配置非法（语言无法识别且不能降级为 plain） | 告警放行 + 提示补 profile | CI 失败 |

`--json` schema（AI 自修循环消费的就是它）：

```json
{
  "path": "src/app.py",
  "lang": "py",
  "ok": false,
  "exit_hint": 1,
  "layers": [
    {"layer": "L2-parse", "ok": false, "tool": "py_compile",
     "issues": [{"line": 42, "col": 1, "code": "unexpected-indent",
                 "msg": "unindent does not match any outer indentation level"}]}
  ],
  "open_stack": [],
  "suggestion": ""
}
```

人类可读输出沿用 bracket_lint 的三件套（首个错点插入符、开括号栈、修复建议）。

### 4.4 检测与拦截流程

**正常路径（闸 1，AI 自修循环）**：

```
AI 执行 Edit/Write
  → agent hook 触发 structure_guard（只查该文件，毫秒级）
      ├─ 退出 0 → 放行，AI 继续
      └─ 退出 1 → hook 以非零退出 + stderr 返回报告
            → agent 收到报告（含行:列+建议）→ 立即修复 → 再次触发检查
            → 最多 3 轮；3 轮仍失败 → 停手向用户报告（防无限循环烧 token）
```

**闸 2（提交拦截）**：pre-commit 取 `git diff --cached --name-only --diff-filter=ACM` → 传给 guard → 退出 1 则阻止提交并打印"按行列修好再 add"；`--no-verify` 逃生口保留（install_hook.py 现成实现）。

**闸 3（CI 兜底）**：`.github/workflows/gate.yml` 在现有 verify 步骤后加一步 `python tools/structure_guard.py $(git ls-files)`，fail-closed。

**失败路径与降级**：L2 权威命令缺失 → 自动降级 L1 并在报告标 `degraded`；L1 对未知扩展名 → `plain` profile（宽松字符串规则，只查平衡，宁漏报不误报）。

### 4.5 集成方式

| 场景 | 动作 |
|---|---|
| **AI agent（首道闸）** | 在 agent 平台的 hooks 配置里挂 PostToolUse（匹配 `Edit|Write` 类工具），命令 `python <技能目录>/structure_guard.py --file <被编辑文件>`（文件路径从 hook 的 stdin JSON 取，具体字段以所用平台 hooks 文档为准）。这一道闸**不需要用户开口**，写入即查——与本项目 SKILL.md §二"写完代码自动 verify"的既定哲学一致 |
| **git 提交闸** | 已有 `install_hook.py --repo .` 一键装（零依赖路径）；或项目已用 pre-commit framework 时加一段 `repo: local` 条目指向同一脚本（两种形态二选一，别叠加） |
| **CI 闸** | `.agents/enforcement/gate.yml` 模板追加一步，随 `tsc install` 落盘 |
| **契约层** | 项目 `AGENTS.md` §2「静态检查」行从"无"改为 `python tools/structure_guard.py <变更文件>`——此后 R-0.1/R-1.2 的"门禁命令"就有了结构维度；已知豁免清单沿用 §2 现有格式 |
| **技能封装** | 新增触发词写进 SKILL.md 触发表：「结构体检 / structure check」→ 对指定文件/目录跑 guard；「装结构门禁」→ install_hook 流程。执行逻辑常驻技能目录，项目里只落 hook 生效件（tsc 架构复刻） |

### 4.6 覆盖场景矩阵

| 故障 | L0 编码 | L1 平衡 | L2 结构 | L3 形态 | L4 断言 |
|---|:-:|:-:|:-:|:-:|:-:|
| 少闭合/多闭合/交叉括号 | | ✅ | ✅ | | |
| 字符串/注释里的括号误报 | | ✅（profile 防误报） | | | |
| 全角括号、弯引号、全角标点 | ✅ | ✅ | | | |
| 未闭合字符串/注释（EOF 类） | | ✅（行列定位） | ✅ | | |
| **平衡但结构残缺**（坑 #75 类） | | 拦不住 | ✅ | ✅（元数规则） | |
| defun/def 嵌套错位（坑 #73 类） | | | ✅ | ✅（顶层规则） | |
| Python 缩进错乱/Tab 混用 | | | ✅（py_compile/ast） | | |
| 编码吞字符（坑 #64 类） | ✅ | | | | |
| 项目特定历史事故复发 | | | | | ✅ |

**明确查不出**（边界诚实）：逻辑错误、变量名拼错、API 误用、语义 bug——那是测试套件与 AGENTS.md 体检流程的职责，本方案不越界（R-3.10 最小改动原则同样适用于职责边界）。

### 4.7 异常处理

| 异常 | 处理 |
|---|---|
| guard 自身崩溃 / 权威工具全缺失 | 退出码 2：闸 1/闸 2 **告警放行**（工具故障不冒充代码问题、不卡交付），闸 3 CI 拦下——fail-closed 由有人的那一层收口 |
| 文件读不了（权限/编码） | utf-8-sig → gbk → latin-1 探测链（bracket_lint `read_text` 现成）；含 NUL 字节判为二进制直接跳过 |
| 超大文件 / 海量问题 | `--max` 截断（现成）+ 文件超过阈值（如 2MB）只跑 L0/L1；闸 1/2 永远只查增量文件，全仓扫描只留给 CI |
| 误报 | 三级豁免：① 项目 §2 已知豁免清单（登记 `命令:条目`，走 PR）；② 行内标记 `# guard:skip <rule>`（仿 noqa，须带理由）；③ 单次 `--no-verify`（install_hook 已提示）。**豁免必须在汇报尾部登记 ID+理由+回滚**，与 R-0.5 同款纪律 |
| profile 覆盖不了的语言 | 降级 `plain`（宽松模式只查平衡），同时提示"该语言无深检，建议补 profile"——降级可见，不许假绿 |
| AI 自修循环不收敛 | 3 轮上限后强制升级人工，报告里附"已尝试轮数 + 每轮首个错误"，防止静默烧 token |
| 检查器自身的可信度 | `--selftest`（26 用例）并入项目 unittest 门禁（`.agents/test/`）——**检查器坏了比没有检查器更危险**，所以它自己的回归必须跑在最高频的门禁里 |

### 4.8 落地路线图

| 阶段 | 内容 | 现状 |
|---|---|---|
| **P0（本周可完成）** | bracket_lint `--selftest` 并入 `.agents/test/`；install_hook 在常用项目铺开 | 两个文件已存在，只差接入 |
| **P1（核心增量）** | `structure_guard.py` 统一入口（L0/L1 直用现有件 + L2 命令表 + 降级链 + `--json`）；agent hook 配置上线 | 新代码约 300~400 行，纯 stdlib |
| **P2（体系化）** | L3 形态插件（先 LISP 家族，按需扩）；L4 断言库模板；gate.yml / AGENTS.md §2 / SKILL.md 触发词三处接入；可选 tree-sitter 增强层 | 按项目语言逐步长出 |

---

## 5. 参考资料

- 本地：`bracket_lint.py`、`install_hook.py`（本项目根）；`HYT-CAD/tools/`（check_lisp / check_sexpr / check_defun_depth / _audit / _collide / check_audit_fixes / make_ansi / check_layer_colors / check_jrt2_out / test_direction）；本项目 `SKILL.md`、`.agents/tsc.py`、`.agents/enforcement/`
- [tree-sitter Query Syntax（ERROR/MISSING 节点）](https://tree-sitter.github.io/tree-sitter/creating-parsers#/query-syntax) · [Zed：低延迟语法感知编辑](https://zed.dev/blog/videogame)
- [Language Models Make Balanced Parentheses Errors（OpenReview 2025）](https://openreview.net)
- [RTLFixer：LLM 生成 RTL 语法错误的自动修复（NVIDIA）](https://github.com/NVlabs/RTLFixer)
- [pre-commit framework](https://pre-commit.com) · [lint-staged](https://github.com/lint-staged/lint-staged) · [Prettier：Pre-commit Hook 官方方案](https://prettier.io/docs/pre-commit)
