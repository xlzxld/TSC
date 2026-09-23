# 执法包 (Enforcement)

> **版本 v5.0.0** | 对应 `AGENTS.md` v5.0.0 的机械执法层：**文档管行为，钩子兜底线**。
> **默认启用**：`tsc.py install` 会自动把本目录的模板落到下表位置，不需要手工拷贝。
> 红线中可机器判定且已落地的项（密钥、提交格式、门禁、主干保护）在此落地；其余红线（如 R-3.1 吞异常、R-3.3 调试残留）由提示词纪律与人工审查兜底。

## 文件去向（`install` 自动完成）

| 模板（技能目录内） | 自动落到目标项目 | 作用 |
|---|---|---|
| `skills/tsc/templates/enforcement/gate.yml` | `.github/workflows/gate.yml` | PR / 主干 push 上的 CI 门禁（含结构门禁步骤）；`branches:` 按 §2「主干分支」自动填 |
| `skills/tsc/templates/enforcement/.pre-commit-config.yaml` | 项目根（同名） | 本地 git 钩子：密钥扫描 + 提交信息规范 + 结构门禁（local 条目） |
| `skills/tsc/templates/enforcement/commitlint.config.js` | 项目根 | Conventional Commits 规则 |
| `skills/tsc/scripts/structure_guard.py` | `.agents/structure_guard.py` | 结构门禁落盘件：AI 代码结构完整性五层检查（括号/语法/缩进/形态） |
| `skills/tsc/scripts/bracket_lint.py` | `.agents/bracket_lint.py` | 结构门禁的 L1 引擎（语言感知括号栈） |

后两份来自技能目录的 `scripts/`（不在本目录）：git 钩子与 CI 只认项目自己的文件，结构门禁必须落盘进项目才能在闸 2/3 生效。**聚合门禁本体不落盘**——由技能目录里的 `scripts/tsc.py verify` 承担（执行逻辑不进项目，由 AI 直接调用）。

## 归属规则（tsc-managed 标记）

五份落盘件都带一行 `# tsc-managed` 标记（`commitlint.config.js` 是 `// tsc-managed`）。落盘后脚本按标记判断归属：

| 项目文件状态 | `install` / `sync` 时的行为 |
|---|---|
| 带 `tsc-managed` 标记 | **技能托管**：上游模板更新时自动覆盖（含 gate.yml 分支名按 §2 重填） |
| 不带标记，但正文与模板一致 | 旧版部署的文件，**一次性升级**为带标记的托管版 |
| 不带标记，且正文与模板不同 | **项目已接管**：永不覆盖，只提示。想换最新模板就自行备份后删掉该文件重跑 `install` |

也就是说：想保留自己的 CI / 钩子配置，就把文件里的标记行删掉再改——之后技能不会再碰它；保持标记就等于把这些文件交给技能长期托管。

## 三层各自拦什么（务必看清边界）

| 层 | 密钥扫描 | 提交信息规范 | 聚合门禁 |
|---|---|---|---|
| **本地钩子** | ✅ 本次暂存的内容 | ✅ 本条提交信息 | ✅ 全跑 |
| **CI (`gate.yml`)** | ✅ **全历史**（gitleaks 官方 action） | ✅ 本次 PR / push 的提交 | ✅ 全跑 |

两点要说清，避免以为"绿了就没事"：

1. **本地钩子的密钥扫描只扫本次暂存内容**，不翻历史。这是刻意的——它拦的是"新密钥进来"。仓库里**已有的旧密钥**它发现不了，那是 CI 那一步（全历史扫描）的职责。
2. **本地钩子不是"可选软开关"。** 一旦执行了 `pre-commit install`，钩子就会真实拦截提交；**依赖没装好时它是报错拦住，不是自动跳过**。所以别把它当成"装了但没配也能凑合跑"。不想被拦就别执行 `install` 那两条命令，只靠 CI。

## 启用步骤

### 1. 装依赖（本地钩子用；不装就别执行第 2 步）

```bash
pip install pre-commit
npm i -D @commitlint/cli @commitlint/config-conventional
```

- key 扫描的钩子由 pre-commit 自己管理，不用手动装 gitleaks。
- 提交信息钩子用 `npx --no -- @commitlint/cli`，**只用本地已装依赖，不联网下载**。
  - ⚠️ 包名必须写 `@commitlint/cli`。写成 `commitlint` 会去下载一个不存在的包并直接失败，把提交堵死。

### 2. 激活本地钩子

```bash
pre-commit install
pre-commit install --hook-type commit-msg
```

### 3. 开分支保护（GitHub：Settings → Branches → Add branch protection rule）

- Branch name pattern 填你的主干分支名，**与 `gate.yml` 的 `branches:` 保持一致**（`install` 已按 §2 自动填好；改过主干名后重跑 `install`）
- 勾选 Require a pull request before merging
- 勾选 Require status checks to pass → 选中 `gate`
- 勾选 Block force pushes

## 日常使用

- AI 完成修改后自动跑聚合门禁（脚本在技能目录），全绿才算闭环（AGENTS.md R-0.1）
- 升级 gitleaks：`pre-commit autoupdate`
- **清理历史里的旧密钥**（本地钩子不管这个）：
  ```bash
  gitleaks git --redact --verbose --log-opts="--all"
  ```

## 已知限制（诚实登记）

- 密钥扫描是**模式匹配**，自定义格式的内网域名、连接串需要自己加规则（gitleaks 的 `--config`），默认规则覆盖不到。
- 本地钩子依赖 Node 与 Python 两个运行时；只在一个平台开发、且不想装的话，靠 CI 那层即可。
- `.pre-commit-config.yaml` 里结构门禁条目的解释器名（`python3` / `python`）是 `install` / `sync`
  时按**部署这台机器**探测后填入的，不是模板写死的值。原因：pre-commit 的 local 钩子只有
  `language: system` 能跑项目内脚本，而 system 语言的 `entry` 首令牌**完全靠系统 PATH 解析**，
  `python3`（macOS / 多数 Linux）与 `python`（Windows 常见）没有交集，写死哪个都只在半边平台成立。
  换平台后重跑一次 `tsc sync` 即可自动校正（内容比对走同一套渲染逻辑，能自愈）。另两条路已实测
  排除：`language: python` 会先对项目根 `pip install .`（没有 `setup.py` / `pyproject.toml` 即失败）；
  `language: script` + 项目内 `sh` 启动器在 Windows 上报 `/bin/sh not found`。
- `gate.yml` 的提交信息校验在 fork PR 上可能拿不到 base sha，此时该步会跳过；主干 push 与同仓库 PR 正常。
- `gate.yml` 的 commitlint 在 `github.event.before` 为全零 SHA（新仓库首次推送等场景）时会因比对范围无效而报错（是显式报错，不是静默放行）；属极边缘场景。
