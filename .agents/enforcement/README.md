# 执法包 (Enforcement)

> **版本 v3.0.0** | 对应 `AGENTS.md` v3.0.0 的机械执法层：**文档管行为，钩子兜底线**。
> **默认启用**：`tsc.py install` 会自动把本目录的模板落到下表位置，不需要手工拷贝。
> 红线中可机器判定且已落地的项（密钥、提交格式、门禁、主干保护）在此落地；其余红线（如 R-3.1 吞异常、R-3.3 调试残留）由提示词纪律与人工审查兜底。

## 文件去向（`install` 自动完成）

| 模板（本目录） | 自动落到目标项目 | 作用 |
|---|---|---|
| `gate.yml` | `.github/workflows/gate.yml` | PR / 主干 push 上的 CI 门禁；`branches:` 按 §2「主干分支」自动填 |
| `.pre-commit-config.yaml` | 项目根（同名） | 本地 git 钩子：密钥扫描 + 提交信息规范 |
| `commitlint.config.js` | 项目根 | Conventional Commits 规则 |

**门禁本体不在这里**——它就是 `.agents/tsc.py verify`，随 `.agents/` 自动同步。

**已存在且被项目改过的文件不会被覆盖**：脚本只提示"内容已被项目改过"并跳过。想强行对齐就自己备份后删掉该文件再重跑 `install`。

## 三层各自拦什么（务必看清边界）

| 层 | 密钥扫描 | 提交信息规范 | 聚合门禁 |
|---|---|---|---|
| **本地钩子** | ✅ 本次暂存的内容 | ✅ 本条第信息 | ✅ 全跑 |
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
- `gate.yml` 的提交信息校验在 fork PR 上可能拿不到 base sha，此时该步会跳过；主干 push 与同仓库 PR 正常。
