# 执法包 (Enforcement)

> **版本 v3.0.0** | 对应 `AGENTS.md` v3.0.0 的**可选**机械执法层：**文档管行为，钩子兜底线**。
> **默认不启用**：本目录里的模板**不在 `tsc.py sync` 的同步范围**，需要时按下面步骤手动放到项目对应位置。
> 红线中可机器判定且已落地的项（密钥、提交格式、门禁、主干保护）在此落地；其余红线（如 R-3.1 吞异常、R-3.3 调试残留）由提示词纪律与人工审查兜底。

## 文件去向

| 模板（本目录） | 拷贝到目标项目 | 作用 |
|---|---|---|
| `gate.yml` | `.github/workflows/gate.yml` | PR 上的 CI 门禁（内部调用 `python3 .agents/tsc.py verify`） |
| `.pre-commit-config.yaml` | 项目根（同名） | pre-commit 框架入口：gitleaks 密钥扫描 + commitlint 提交信息校验 |
| `commitlint.config.js` | 项目根 | Conventional Commits 规则 |

**门禁本体不在这里**——它就是 `.agents/tsc.py verify`，随 `.agents/` 自动同步，不需要手工拷贝，也不再有 `Makefile`。

## 启用步骤（可选，按需）

1. **拷贝**：按上表把需要的文件复制到目标项目对应位置。
2. **本地钩子（可选）**：`pip install pre-commit && pre-commit install && pre-commit install --hook-type commit-msg`；commitlint 钩子以 `npx --no` 运行（不联网下载），须先本地安装：`npm i -D @commitlint/cli @commitlint/config-conventional`
   - `.pre-commit-config.yaml` 依赖 `commitlint.config.js`，两个要一起拷。
   - **不想装 Node 与 Python 两个包就跳过本地钩子**，靠 CI 兜底——`gate.yml` 已写成"有配置才扫"，跳过不会报错。
3. **门禁命令**：填 `.agents/project.py`（`install` 时已自动生成），与 `AGENTS.md` §2 保持一致，用 `python3 .agents/tsc.py check-config` 校验。
4. **分支保护**（GitHub：Settings → Branches → Add branch protection rule）：
   - Branch name pattern 填你的主干分支名，**与 `gate.yml` 顶部的 `branches:` 保持一致**（默认写的是 `main`，主干不叫 main 的项目必须改）
   - 勾选 Require a pull request before merging
   - 勾选 Require status checks to pass → 选中 `gate`
   - 勾选 Block force pushes

## 日常使用

- AI 完成修改后执行 `python3 .agents/tsc.py verify`，全绿才算闭环（AGENTS.md R-0.1）
- 升级 gitleaks：`pre-commit autoupdate`
- 离线环境：步骤 2 已将 commitlint 本地化（`npx --no` 不访问网络）；若偏好在线按需下载，把 `.pre-commit-config.yaml` 中 entry 改为 `npx -- commitlint --edit`

## 覆盖对照

| 契约规则 | 执法手段 |
|---|---|
| R-0.4 禁止泄露密钥 | gitleaks（密钥类部分覆盖；内网域名 / 连接串须自定义规则或人工审查） |
| R-3.8 原子提交 / Conventional Commits | commitlint（commit-msg 钩子） |
| R-0.1 未验证不交付 | `python3 .agents/tsc.py verify` 聚合门禁 |
| 主干保护（§2） | branch protection + gate CI |
