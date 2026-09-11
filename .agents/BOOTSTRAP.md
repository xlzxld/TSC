# 规范部署与适配生成器 (BOOTSTRAP.md)

> **版本 v3.1.2** | 与仓库根 `AGENTS.md` v3.1.2、`.agents/AUDIT-SPEC.md` 配套。
> **单源原则**：本文件**不内嵌**契约模板。母版 = 仓库根 `AGENTS.md`；执行逻辑常驻技能目录（`<SKILL_DIR>/.agents/`），**不复制进项目**。契约只有一个真身，禁止再复制出第二份。
> **使用方法**：由 AI 代跑 `python3 "<SKILL_DIR>/.agents/tsc.py" install --from "<SKILL_DIR>" --project <项目根>`（建议先加 `--dry-run` 看变化），然后说"适配 / 初始化规范"；或直接说"读取通用母版，自动扫描当前项目，生成定制化 AGENTS.md。有无法确定的配置再问我。"

---

## 阶段 0：探测目标项目特征（静默执行，不输出废话）

1. **语言与运行时**：检查根目录 `package.json` (Node/TS)、`Cargo.toml` (Rust)、`go.mod` (Go)、`pyproject.toml`/`requirements.txt` (Python)、`pom.xml`/`build.gradle` (Java)、`*.csproj` (C#)。
2. **真实门禁命令**：
   - 测试：`npm test` / `pytest` / `go test ./...` / `cargo test` / `python -m unittest discover`
   - 静态检查：`npm run lint` / `ruff check` / `golangci-lint run` / `cargo clippy`
   - 格式化：**只登记 `--check` 等价命令**（`prettier --check` / `black --check` / `cargo fmt --check`），禁止登记写模式命令
   - 构建：`npm run build` / `cargo build`
3. **主干分支**：`git branch` / `git remote show origin`。
4. **平台命令名**：确认目标机器上 Python 命令是 `python`（Windows 常见）还是 `python3`（macOS 常见），据此填 `.agents/project.py`。
5. **裸源码兜底**：无任何 manifest 时按文件后缀推断语言（`.py`→Python、`.ts`/`.js`→Node、`.go`→Go、`.rs`→Rust），并在 §2 如实登记探测依据，禁止臆造。

## 阶段 1：模式判定（三选一，禁止混淆）

- **模式 A（新项目部署）**：目标项目根目录**无** AGENTS.md → 用 `tsc.py install` 落地部署单元（根目录 `AGENTS.md` + 项目内 `.agents/`仅配置 + 执法包落盘件；执行逻辑不进项目），再执行阶段 3 填充。
- **模式 B（已有契约适配）**：目标项目根目录**已有** AGENTS.md → 用 `tsc.py sync` 重新合成，**仅重算其 §2 表格**，输出修改前后 diff，等待确认后才写入；禁止全文覆盖，禁止触碰 §0 / §1 / §3 / §4 / §5。
- **模式 C（契约版本升级）**：目标项目已有**旧版本**本契约 → 用 `tsc.py sync` 整体同步升级，仅保留项目的 §2 取值，输出版本级 diff，确认后写入；禁止静默丢弃项目定制。旧结构（根目录散着的 `AUDIT-SPEC.md` / `BOOTSTRAP.md` / `enforcement/` / `test/`）由 `sync` 自动搬进 `.agents/`，**不自动删除任何文件**，只打印建议人工删除清单。

## 阶段 2：人机对齐门禁（极简）

仅当存在**多重工具冲突**（既装 Jest 又装 Vitest、多语言 Monorepo）才提问，最多 1~2 个选择题；严禁拿显而易见的信息打扰用户。

## 阶段 3：填充与校验

1. 用阶段 0 探测结果填充 AGENTS.md §2；探测不到的项如实写"无"或向用户提问，**禁止臆造**。
2. 把同样的取值填进 `.agents/project.py`（四条命令变量），然后由 AI 代跑 `tsc.py check-config`——**§2 表格与 project.py 必须同源**，不一致会退出码 1，禁止只改一处。
3. 校验（模式 A / B / C 均适用）：`wc -l AGENTS.md` < 80（LF 计）；`tsc.py verify` 在终端实测可执行（附退出码）。两命令均从 `<SKILL_DIR>/.agents/tsc.py` 调用、以 `--project` 指向目标项目。
4. 目标项目存在基线失败（存量 lint 警告、跳过测试）时，登记进"已知豁免清单"行——**只登记，不放宽验证条件**。

## 阶段 4：完成反馈（如实陈述，禁止绝对化承诺）

输出三件事：部署/更新了哪些文件；§2 与 `project.py` 各项取值的来源（探测文件 / 用户确认）；遗留未决项清单。

> 禁止使用"AI 将全自动遵守此契约"等话术——契约降低违规概率，机械执法兜住底线：
> 密钥泄露 → gitleaks（`.agents/enforcement/.pre-commit-config.yaml` 已随 `install` 自动落盘，或 CI）；Conventional Commits → commitlint（同上）；主干保护 → branch protection（须人工开）；闭环验证 → 一条聚合命令，由 AI 自动执行。
