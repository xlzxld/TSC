# tsc —— AI 行为契约技能

一套让 AI 编码助手在项目里守规矩的契约，加一个能跑的门禁。**仓库本身就是技能**：不需要打包，装到哪里就是哪里的技能。

```
tsc/                          ← 仓库根 = 技能根
├─ SKILL.md                   # 技能定义（name: tsc）
├─ AGENTS.md                  # 契约母版（分发到项目根）
├─ VERSION                    # 版本号单源
├─ CHANGELOG.md               # 变更记录
├─ 使用手册.md                # 给人看的说明书
└─ .agents/                   # 上游内容（整目录分发）
   ├─ tsc.py                  # 唯一核心：install / sync / verify / status / check-config
   ├─ project.example.py      # 项目门禁命令模板
   ├─ verify.ps1  verify.sh   # 系统入口薄壳
   ├─ AUDIT-SPEC.md           # 体检细则
   ├─ BOOTSTRAP.md            # 适配流程
   ├─ enforcement/            # 可选的机械执法层（CI / git 钩子）
   └─ test/                   # 契约自身的题库
```

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

更新技能 = 在技能目录里 `git pull`。**没有打包、没有构建步骤。**

## 二、在项目里使用（一句话调用）

装好技能后，**你不需要敲任何命令**。在项目里对 AI 说一句话就行：

| 你说 | AI 会做 |
| --- | --- |
| **"接入契约"** | 先 `--dry-run` 给你看将改动什么，你点头后真正写入（含执法包） |
| **"同步契约"** | 拉上游最新内容合并，**你的 §2 不会被覆盖** |
| **"体检"** | 全仓只读扫描，输出 P0~P3 问题表后停下等你点单 |
| **"修复 A-01"** | 按表修，改完自动跑门禁，带证据汇报 |
| **"契约状态"** / `tsc` | 报告接没接入、什么版本、§2 填好没 |

**跑门禁不需要你说**。AI 每次改完文件会自动跑 `verify`，提交前必须退出码 0 才算完成（这就是 R-0.1 的落地方式）。`python` / `python3` 的差异、路径怎么拼，也全是 AI 的事。

<details>
<summary>兜底：手敲命令（CI 或 AI 不在场时用）</summary>

```bash
python3 .agents/tsc.py status          # 看状态：接没接入、什么版本、§2 填好没
python3 .agents/tsc.py install --from "<技能目录>"   # 首次接入（含执法包）
python3 .agents/tsc.py sync  --from "<技能目录>"     # 上游更新后同步
python3 .agents/tsc.py verify          # 跑聚合门禁
python3 .agents/tsc.py check-config    # 校验 §2 与 project.py 是否同源
```

- **Windows** 用 `python`，**macOS** 用 `python3`；不想记差异就敲 `.agents\verify.ps1` 或 `.agents/verify.sh`。
- 首次执行 `install` / `sync` 建议先加 `--dry-run`，只报告不写盘。

</details>

### 接入后的项目结构

```
<项目根>/
├─ AGENTS.md                       # 契约本体 + 项目自己的 §2（§2 永不被覆盖）
├─ .pre-commit-config.yaml         # ← 执法包自动落盘
├─ commitlint.config.js            # ← 执法包自动落盘
├─ .github/workflows/gate.yml      # ← 执法包自动落盘（CI 门禁）
└─ .agents/                        # 上游整目录同步
   ├─ VERSION  tsc.py  project.py
   ├─ AUDIT-SPEC.md  BOOTSTRAP.md
   └─ enforcement/  test/
```

**根目录从原来的 4 项（3 文档 + 1 目录）降到 2 项**——但执法包的三份文件会按上表落到生效位置，那是"生效"而不是"散落"，且由 `install` 自动完成。

### 接入后必做一次的一件事

`.agents/project.py` 生成时四条命令都是 `None`。填成本项目真实的命令，否则门禁全程 skip，会给出"全绿"的假结论：

```python
import sys
PY = "python" if sys.platform == "win32" else "python3"
FMT_CHECK_CMD = "npx prettier --check ."
LINT_CMD      = "npx eslint ."
TEST_CMD      = f"{PY} -m pytest"
BUILD_CMD     = None          # 没有就写 None
```

填完对 AI 说一句"跑一下 check-config"，或直接手敲 `python3 .agents/tsc.py check-config`。

## 三、退出码（脚本的唯一判定口径）

| 码 | 含义 |
| --- | --- |
| 0 | 成功 / 已是最新 |
| 1 | §2 结构有变更，需人工合并（**脚本不会写任何文件**） |
| 2 | IO / 编码 / 权限错误 |
| 3 | 状态非法（缺 §2、缺 VERSION、找不到上游） |

## 四、机械执法层（默认安装）

`.agents/enforcement/` 里的模板由 `install` **自动落到生效位置**，不用手工拷贝：

| 模板 | 自动落到 | 作用 |
| --- | --- | --- |
| `gate.yml` | `.github/workflows/gate.yml` | PR 上的 CI 门禁；`branches:` 按 §2「主干分支」自动填 |
| `.pre-commit-config.yaml` | 项目根（同名） | 本地 gitleaks 密钥扫描 + commitlint |
| `commitlint.config.js` | 项目根 | Conventional Commits 规则 |

已存在且被项目改过的文件**不会被覆盖**，脚本只提示并跳过。

落盘后还剩两件人工的事：① 先 `pip install pre-commit` + `npm i -D @commitlint/cli @commitlint/config-conventional`，再跑 `pre-commit install && pre-commit install --hook-type commit-msg` 激活本地钩子；② 在 GitHub 开分支保护。细节见 `.agents/enforcement/README.md`。

> ⚠️ 本地钩子**不是"装上但没配也能凑合"**：一旦激活，依赖缺失会让提交直接失败（不是自动跳过）。不想被拦就别执行那两条 `install` 命令，只靠 CI 那层。

## 五、维护本仓库（发版）

1. 改完内容后同步 `VERSION` 与三处版本头（`AGENTS.md` / `.agents/AUDIT-SPEC.md` / `.agents/BOOTSTRAP.md`）。
2. 在仓库里跑一次 `python3 .agents/tsc.py sync --from .`，让 `.agents/VERSION` 跟上（版本号不一致时它会自动补写）。
3. 在 `CHANGELOG.md` 顶部记一笔。
4. 校验：`wc -l AGENTS.md` 必须 < 80；`python3 .agents/tsc.py verify` 退出码 0；`check-config` 退出码 0。
5. 提交走 Conventional Commits；标签用**扁平名**（`v3.0.0`，不要 `release/v3.0.0`）。
6. 推送到 GitHub 需走代理：`git -c http.proxy=http://127.0.0.1:7897 -c https.proxy=http://127.0.0.1:7897 push origin <分支>`

## 六、已知限制

- 上游来源只支持**本地路径**，不支持 git URL 直连（避免代理与网络依赖；技能目录本身就是上游）。
- `sync` 以 `VERSION` 判断是否需要更新：版本号相同即跳过，不比对内容。
- 暂未适配 Linux。
