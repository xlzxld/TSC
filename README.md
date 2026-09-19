# tsc —— AI 行为契约技能

一套让 AI 编码助手在项目里守规矩的契约，加一个能跑的门禁。**仓库本身就是技能**：不需要打包，装到哪里就是哪里的技能。

```
tsc/                          ← 仓库根 = 技能根（执行逻辑都在这儿）
├─ SKILL.md                   # 技能定义（name: tsc）
├─ AGENTS.md                  # 契约母版（分发到项目根）
├─ structure_guard.py         # 结构门禁统一入口（正本；随 install 落盘进项目）
├─ bracket_lint.py            # 结构门禁 L1 引擎（正本；随 install 落盘进项目）
├─ install_hook.py            # 闸2 安装器：给项目装 pre-commit 结构门禁
├─ VERSION                    # 版本号单源
├─ CHANGELOG.md               # 变更记录
├─ 使用手册.md                # 给人看的说明书
└─ .agents/                   # 上游内容
   ├─ tsc.py                  # 唯一核心：install / sync / verify / status / check-config
   ├─ project.example.py      # 项目门禁命令模板
   ├─ verify.ps1  verify.sh   # 系统入口薄壳
   ├─ AUDIT-SPEC.md           # 体检细则
   ├─ BOOTSTRAP.md            # 适配流程
   ├─ AI代码结构完整性防护方案.md  # 结构门禁设计文档（历史依据）
   ├─ enforcement/            # 机械执法层模板（落盘件随 install 部署）
   └─ test/                   # 契约自身的题库
```

**注意分工**：上面这些**只有 `AGENTS.md`、执法包三份落盘件与结构门禁两份落盘件会进项目**（共 9 个文件）。`tsc.py`、`install_hook.py`、`AUDIT-SPEC.md`、`BOOTSTRAP.md`、`verify.*`、`test/`、`enforcement/` 模板原件都常驻技能目录——技能既然已经装在平台上，没必要再往每个项目复制一份。

## 一、安装技能

把仓库放到目标平台的技能目录即可：

| 平台 | 技能目录 |
| --- | --- |
| WorkBuddy | `~/.workbuddy/skills/tsc/` |
| Claude Code | `~/.claude/skills/tsc/` |
| Windows 上的 Claude Code | `%USERPROFILE%\.claude\skills\tsc\` |

```bash
# 有网（本机访问 GitHub 需走代理，一次性参数，不写配置）
git -c http.proxy=http://127.0.0.1:7897 -c https.proxy=http://127.0.0.1:7897 \
    clone <仓库地址> ~/.claude/skills/tsc

# 离线：直接把仓库目录整个拷进技能目录即可
```

更新技能 = 在技能目录里 `git pull`（同样带上面的代理参数）。**没有打包、没有构建步骤。** 更新后在任何接了契约的项目里对 AI 说一句"**更新契约**"，它会先 pull 技能目录、再把新内容 sync 进项目。

## 二、在项目里使用（一句话调用）

装好技能后，**你不需要敲任何命令**。在项目里对 AI 说一句话就行：

| 你说 | AI 会做 |
| --- | --- |
| **"接入契约"** | 先 `--dry-run` 给你看将改动什么，你点头后真正写入（含执法包与结构门禁落盘件） |
| **"更新契约"** | 先在技能目录 `git pull` 拉远程最新版，再走"同步契约"流程 |
| **"同步契约"** | 拉本地技能目录的最新内容合并，**你的 §2 不会被覆盖** |
| **"体检"** | 全仓只读扫描，输出 P0~P3 问题表后停下等你点单 |
| **"修复 A-01"** | 按表修，改完自动跑门禁，带证据汇报 |
| **"结构体检"** | 对指定文件/目录跑结构完整性检查（只读） |
| **"装结构门禁"** | 给项目装 pre-commit 钩子 + 接 AI 编辑后自动检查 |
| **"契约状态"** / `tsc` | 报告接没接入、什么版本、§2 填好没 |

**跑门禁不需要你说**。AI 每次改完文件会自动跑 `verify`，提交前必须退出码 0 才算完成（这就是 R-0.1 的落地方式）。`python` / `python3` 的差异、路径怎么拼，也全是 AI 的事。

<details>
<summary>兜底：手敲命令（CI 或 AI 不在场时用）</summary>

脚本常驻技能目录，用 `--project` 指目标项目（省略则取当前目录）：

```bash
SK=~/.claude/skills/tsc            # 换成你的技能目录
python3 "$SK/.agents/tsc.py" status       --project <项目根>   # 看状态
python3 "$SK/.agents/tsc.py" install      --from "$SK" --project <项目根>   # 首次接入
python3 "$SK/.agents/tsc.py" sync         --from "$SK" --project <项目根>   # 上游更新后同步
python3 "$SK/.agents/tsc.py" verify       --project <项目根>   # 跑聚合门禁
python3 "$SK/.agents/tsc.py" check-config --project <项目根>   # 校验 §2 与 project.py 同源
```

- **Windows** 用 `python`，**macOS** 用 `python3`。
- 首次执行 `install` / `sync` 建议先加 `--dry-run`，只报告不写盘。

</details>

### 接入后的项目结构

```
<项目根>/
├─ AGENTS.md                       # 契约本体 + 项目自己的 §2（§2 永不被覆盖）
├─ .pre-commit-config.yaml         # ← 执法包自动落盘（git 钩子只能读项目自己的文件）
├─ commitlint.config.js            # ← 执法包自动落盘
├─ .github/workflows/gate.yml      # ← 执法包自动落盘（CI 只能读项目自己的文件）
└─ .agents/
   ├─ project.py                   # 本项目自己的门禁命令
   ├─ structure_guard.py           # ← 结构门禁落盘件（闸2 钩子与闸3 CI 读它）
   ├─ bracket_lint.py              # ← 结构门禁 L1 引擎落盘件
   ├─ VERSION                      # 版本号，供 sync 比对
   └─ .source                      # 记录上游在哪
```

**整个项目只多 9 个文件，约 50KB。** 执行逻辑（`tsc.py`、`install_hook.py` 等）不再进项目——它们在技能目录里，AI 直接调用即可。

> 首次铺设时若发现项目里还留着旧版复制进来的执行逻辑，脚本会**列出来提示**，但**不会自动删**（契约 R-3.4）。确认后你自己删掉即可，留着也不影响功能。

### 接入后必做一次的一件事

新装项目的 §2 取值列全是 `[自动填充]` 占位，`.agents/project.py` 四条命令都是 `None`。**两处都要填成本项目真实取值**，否则门禁全程 skip 会给出"全绿"的假结论：

```python
import sys
PY = "python" if sys.platform == "win32" else "python3"
FMT_CHECK_CMD = "npx prettier --check ."
LINT_CMD      = "npx eslint ."
TEST_CMD      = f"{PY} -m pytest"
BUILD_CMD     = None          # 没有就写 None
```

填完对 AI 说一句"跑一下 check-config"，或直接手敲 `python3 "<技能目录>/.agents/tsc.py" check-config`。

## 三、退出码（脚本的唯一判定口径）

| 码 | 含义 |
| --- | --- |
| 0 | 成功 / 已是最新 |
| 1 | §2 结构有变更，需人工合并（**脚本不会写任何文件**） |
| 2 | IO / 编码 / 权限错误 |
| 3 | 状态非法（缺 §2、缺 VERSION、找不到上游、门禁全未配置） |

## 四、机械执法层（默认安装）

`.agents/enforcement/` 里的模板与结构门禁脚本由 `install` **自动落到生效位置**，不用手工拷贝（模板原件留在技能目录，只落生效件）：

| 模板 | 自动落到 | 作用 |
|---|---|---|
| `gate.yml` | 项目的 `.github/workflows/gate.yml` | PR / 主干 push 上的 CI 门禁（含结构门禁步骤）；`branches:` 按 §2「主干分支」自动填 |
| `.pre-commit-config.yaml` | 项目根（同名） | 本地 gitleaks 密钥扫描 + commitlint |
| `commitlint.config.js` | 项目根 | Conventional Commits 规则 |
| `structure_guard.py` | 项目的 `.agents/structure_guard.py` | 结构门禁：AI 代码结构完整性五层检查（git 钩子与 CI 够不着技能目录，必须落盘进项目） |
| `bracket_lint.py` | 项目的 `.agents/bracket_lint.py` | 结构门禁的 L1 引擎（同上） |

五份落盘件都带 `tsc-managed` 标记行，按标记决定归属：**带标记 = 技能托管**，`install` / `sync` 时随上游模板自动覆盖更新；**不带标记且内容与模板不同 = 项目已接管**，技能永不覆盖只提示（想换最新模板就自行备份后删掉该文件重跑 `install`）。

落盘后还剩两件人工的事：① 先 `pip install pre-commit` + `npm i -D @commitlint/cli @commitlint/config-conventional`，再跑 `pre-commit install && pre-commit install --hook-type commit-msg` 激活本地钩子；② 在 GitHub 开分支保护。细节见技能目录里的 `.agents/enforcement/README.md`。

> ⚠️ 本地钩子**不是"装上但没配也能凑合"**：一旦激活，依赖缺失会让提交直接失败（不是自动跳过）。不想被拦就别执行那两条 `install` 命令，只靠 CI 那层。

## 五、维护本仓库（发版）

1. 改完内容后同步 `VERSION` 与六处版本头（`AGENTS.md` / `.agents/AUDIT-SPEC.md` / `.agents/BOOTSTRAP.md` / `.agents/enforcement/README.md` / `SKILL.md` 的 `version:` / `使用手册.md` 首部）。
2. 在仓库里跑一次 `python3 .agents/tsc.py sync --from .`，让 `.agents/VERSION` 跟上（版本号不一致时它会自动补写）。
3. 在 `CHANGELOG.md` 顶部记一笔。
4. 校验：`wc -l AGENTS.md` 必须 < 80；`python3 .agents/tsc.py verify` 退出码 0；`check-config` 退出码 0。
5. 提交走 Conventional Commits；标签用**扁平名**（`v3.0.0`，不要 `release/v3.0.0`）。
6. 推送到 GitHub 需走代理：`git -c http.proxy=http://127.0.0.1:7897 -c https.proxy=http://127.0.0.1:7897 push origin <分支>`

## 六、已知限制

- 上游来源只支持**本地路径**，不支持 git URL 直连（避免代理与网络依赖；技能目录本身就是上游，远程更新走"技能目录 git pull + 项目 sync"两步，技能触发词"更新契约"已把两步串起来）。项目 `.agents/.source` 记录的路径失效时（技能目录搬家）自动回退到脚本所在仓库，`install` / `sync` 成功后顺手把记录修正为实际使用的上游。
- `sync` 的同步判据是**逐项内容漂移比对**（v3.2.0 起），不是版本号：上游改了内容但忘 bump 版本，sync 照样把差异写下去。
- **项目不再自包含**：项目里没有执行逻辑，门禁靠技能目录里的 `tsc.py` 跑（结构门禁落盘件除外——它是钩子与 CI 的生效件，自身可独立运行）。换机器时先装技能，否则项目的门禁跑不了（本地钩子与 CI 落盘件不受影响，CI 门禁照常跑）。
- 平台：Windows 已实测；macOS / Linux 仅用标准库、无平台专属调用，尚未实测（发版待办已登记）。
