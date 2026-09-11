# 执法包 (Enforcement)

> **版本 v3.0.0** | 对应 `AGENTS.md` v3.0.0 的机械执法层：**文档管行为，钩子兜底线**。
> **默认启用**：`tsc.py install` 会自动把本目录的三份模板落到下表位置，不需要手工拷贝。
> （`sync` 也会补齐；只动了 `.agents/enforcement/` 下的上游模板时，按版本相同则跳过，需要时用 `install` 强制重落。）
> 红线中可机器判定且已落地的项（密钥、提交格式、门禁、主干保护）在此落地；其余红线（如 R-3.1 吞异常、R-3.3 调试残留）由提示词纪律与人工审查兜底。

## 文件去向（`install` 自动完成）

| 模板（本目录） | 自动落到目标项目 | 作用 |
|---|---|---|
| `gate.yml` | `.github/workflows/gate.yml` | PR 上的 CI 门禁（内部调用 `python3 .agents/tsc.py verify`）；`branches:` 按 §2「主干分支」自动填 |
| `.pre-commit-config.yaml` | 项目根（同名） | pre-commit 框架入口：gitleaks 密钥扫描 + commitlint 提交信息校验 |
| `commitlint.config.js` | 项目根 | Conventional Commits 规则 |

**门禁本体不在这里**——它就是 `.agents/tsc.py verify`，随 `.agents/` 自动同步，不需要手工拷贝，也不再有 `Makefile`。

**已存在且被项目改过的文件不会被覆盖**：脚本只提示"内容已被项目改过"并跳过，避免把你的 CI 配置冲掉。想强行对齐就自己备份后删掉该文件再重跑 `install`。

## 剩下两件只能人工做的事

自动化到落盘为止，下面两步脚本做不了：

1. **激活本地钩子**（可选，但推荐）：
   ```bash
   pip install pre-commit
   pre-commit install
   pre-commit install --hook-type commit-msg
   npm i -D @commitlint/cli @commitlint/config-conventional
   ```
   - `.pre-commit-config.yaml` 依赖 `commitlint.config.js`，两个都已自动落盘。
   - **不想装 Node 与 Python 两个包就跳过**，靠 CI 兜底——`gate.yml` 已写成"有配置才扫"，跳过不会报错。
2. **开分支保护**（GitHub：Settings → Branches → Add branch protection rule）：
   - Branch name pattern 填你的主干分支名，**与 `gate.yml` 顶部的 `branches:` 保持一致**（`install` 已按 §2 自动填好；改过主干名后重跑 `install`）
   - 勾选 Require a pull request before merging
   - 勾选 Require status checks to pass → 选中 `gate`
   - 勾选 Block force pushes

## 日常使用

- AI 完成修改后自动执行 `python3 .agents/tsc.py verify`，全绿才算闭环（AGENTS.md R-0.1）
- 升级 gitleaks：`pre-commit autoupdate`
- 离线环境：commitlint 钩子以 `npx --no` 运行（不访问网络）；若偏好在线按需下载，把 `.pre-commit-config.yaml` 中 entry 改为 `npx -- commitlint --edit`

## 覆盖对照

| 契约规则 | 执法手段 |
|---|---|
| R-0.4 禁止泄露密钥 | gitleaks（密钥类部分覆盖；内网域名 / 连接串须自定义规则或人工审查） |
| R-3.8 原子提交 / Conventional Commits | commitlint（commit-msg 钩子） |
| R-0.1 未验证不交付 | `python3 .agents/tsc.py verify` 聚合门禁 |
| 主干保护（§2） | branch protection + gate CI |
