# TSC —— AI 行为契约插件（Agent Skill / ZCode Plugin）

一套让 AI 编码助手在项目里守规矩的契约，加一个能跑的门禁。TSC 是一个标准 ZCode 插件（内含可独立发现的 Agent Skill）：装一次，之后在**任何项目**里用一句话完成接入、同步、升级、回滚。

## 目录结构

```
TSC/
├─ .zcode-plugin/plugin.json   # 插件清单（name/version/组件声明）
├─ marketplace.json            # 插件市场目录（GitHub 仓库可直接作为市场添加）
├─ skills/tsc/SKILL.md         # 技能定义（自然语言触发的路由层）
├─ skills/tsc/references/      # AUDIT-SPEC.md（体检）/ BOOTSTRAP.md（项目探测填充）
├─ commands/                   # /tsc、/tsc-update、/tsc-sync、/tsc-status
├─ hooks/hooks.json            # 插件 Hook：AI 编辑后自动跑结构门禁（${ZCODE_PLUGIN_ROOT}）
├─ scripts/                    # 实现：tsc.py（唯一 CLI）、structure_guard.py、bracket_lint.py、install_hook.py
├─ templates/                  # 项目落盘模板：AGENTS.md、project.example.py、enforcement/
├─ tests/unit  tests/e2e       # 快速单测（<10s）/ 端到端回归（<30s）
├─ docs/                       # MANUAL_CN.md 使用手册、结构门禁设计、评测材料
├─ AGENTS.md                   # 本仓库自己的契约实例（母版在 templates/AGENTS.md）
├─ VERSION                     # 版本发布唯一真源
└─ CHANGELOG.md
```

**两层边界**：Skill/Plugin 本体（本仓库）负责实现与升级；项目契约（`AGENTS.md` + `.agents/project.py` + 执法包落盘件，共 8 个文件，Node 项目多 1 个）安装进具体项目。执行逻辑永不复制进项目。

## 安装 / 使用

**安装 TSC**：ZCode → 插件市场 → 添加 → 添加插件市场 → 粘贴 `https://github.com/xlzxld/TSC`（或本地目录）→ 在"个人"页安装 `tsc`。其他平台可把仓库整体拷进其技能目录（如 `~/.claude/skills/tsc/`）。

装好后对 AI 说一句话（无需敲命令）：

| 你说 | AI 做 |
| --- | --- |
| **"接入契约"** | 探测项目 → `install --dry-run` 预览 → 确认后写入契约 + 执法包 → 填 §2 → `verify` + `doctor` |
| **"更新 TSC"** | 只升级本体（git 安装副本自动 pull；市场安装副本提示走 设置 → 插件管理 → 更新） |
| **"更新契约" / "同步契约"** | 把当前已安装 TSC 同步进项目（`sync`，只认当前本体，不联网、不看项目 `.source`） |
| **"升级 TSC，并同步当前项目"** | 一句话完整升级链：升本体 → 同步项目 → 门禁 → 汇报版本变化 |
| **"回滚契约"** | `rollback`：撤销最近一次 install/sync 的写入 |
| **"契约状态"** / `/tsc` | `status` + `doctor`（ready / not-ready 结论） |
| **"体检"** | 只读审计，输出问题清单后停下等确认 |

## 所有权与安全边界

- 项目 `AGENTS.md` 带 `<!-- tsc-managed-contract:v4 -->` 标记 = TSC 托管，可随本体升级同步（§2 项目取值永不覆盖）。
- **没有标记的外部 AGENTS.md 默认只读**：`sync`/`install` 拒绝接管并输出冲突摘要；仅 `install --force`（显式确认）接管。
- 旧版（v3.x）部署的项目没有标记但有 `.agents/VERSION`：首次 `sync` 自动补标记、一次性升级——`.agents/.source`（无论指向多旧的上游、失效与否）都只是历史记录，绝不参与选源。
- 执法包文件带 `tsc-managed` 标记随模板更新；被项目改掉标记的文件永不覆盖。
- **纯 Python 等非 Node 项目不部署 commitlint、不引入任何 npm 依赖**（CI 的 commitlint 步骤只认 `commitlint.config.js` 是否存在）。
- `verify` 的每条门禁命令都有超时（默认 600s，`--timeout` 或 project.py 的 `GATE_TIMEOUTS` 可调）：超时杀整个进程组，退出码 124，绝不无限等待。
- install/sync 全程内存 journal，任一步写盘失败整体回滚；成功后留 `.agents/.tsc-backup/`，`rollback` 可撤销。

## CLI（供 CI / 手工兜底）

```bash
SK=<TSC 插件目录>
python3 "$SK/scripts/tsc.py" status      --project <项目根>   # 状态（--json 机器可读）
python3 "$SK/scripts/tsc.py" install     --project <项目根>   # 首次接入（外部 AGENTS.md 接管加 --force）
python3 "$SK/scripts/tsc.py" sync        --project <项目根>   # 项目契约同步到当前本体
python3 "$SK/scripts/tsc.py" update                           # 只升级本体（git pull --ff-only，带超时）
python3 "$SK/scripts/tsc.py" verify      --project <项目根>   # 聚合门禁（每条命令带超时）
python3 "$SK/scripts/tsc.py" check-config --project <项目根>  # §2 与 project.py 同源校验
python3 "$SK/scripts/tsc.py" doctor      --project <项目根>   # 只读诊断：ready / not-ready
python3 "$SK/scripts/tsc.py" rollback    --project <项目根>   # 撤销最近一次 install/sync
```

退出码：`0` 成功/已是最新；`1` 需人工处理（§2 结构变更、外部 AGENTS.md 未接管、§2 与 project.py 不一致）；`2` IO/权限错误；`3` 状态非法；`124` 门禁命令超时。Windows 把 `python3` 写成 `python`。

## 维护本仓库（发版）

1. 改 `templates/AGENTS.md`（母版）与 `scripts/`，bump 根 `VERSION` 与 `.zcode-plugin/plugin.json`、`marketplace.json` 的 version（三处必须一致，测试强制）。
2. 在仓库根跑 `python3 scripts/tsc.py sync --project .` 自举（生成 gitignore 掉的 `.agents/VERSION`/`.source`，根 AGENTS.md 与模板校验零漂移）。
3. `CHANGELOG.md` 顶部记一笔。
4. 门禁：`wc -l AGENTS.md` < 80；`python3 scripts/tsc.py verify` 退出码 0（含 unit + e2e）。
5. 提交走 Conventional Commits；标签用扁平名（`v4.0.0`）。

## 平台支持

- macOS：已实测（本版本发布平台）。
- Linux：标准库实现，无平台专属调用；CI（gate.yml）跑在 ubuntu-latest。
- Windows：v3.x 已实测过核心同步逻辑；v4 重组后待实测。插件 Hook 固定用 `python3` 调结构门禁；Windows 用户如无 `python3` 命令，可在项目 `.zcode/config.json` 配同名 workspace Hook 改用 `python`（README 不假定该平台已验证）。
