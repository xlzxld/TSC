# TSC —— AI 行为契约技能（通用 Agent Skill）

一套让 AI 编码助手在项目里守规矩的契约，加一个能跑的门禁。装一次，之后在**任何项目**里用一句话完成接入、同步、升级、回滚。

**通用技能**：本仓库就是一个标准 Agent Skill——技能目录 `skills/tsc/` 自包含（技能定义 + 执行脚本 + 落盘模板 + 深度参考），**不含任何平台私有清单**。拷这一个目录进宿主的技能目录即可使用，不绑定某个编辑器/插件市场。

## 目录结构

```
TSC/
├─ skills/tsc/                  # 【技能本体】自包含，拷这个目录就能用
│  ├─ SKILL.md                  # 技能定义（自然语言触发的路由层）
│  ├─ VERSION                   # 版本发布唯一真源
│  ├─ scripts/                  # 实现：tsc.py（唯一 CLI）、structure_guard.py、bracket_lint.py、install_hook.py
│  ├─ templates/                # 项目落盘模板：AGENTS.md、project.example.py、enforcement/
│  ├─ references/               # AUDIT-SPEC.md（体检）/ BOOTSTRAP.md（项目探测填充）
│  └─ commands/                 # 可选的斜杠命令（宿主支持命令文件时才生效）
├─ AGENTS.md                    # 本仓库自己的契约实例（母版在 skills/tsc/templates/AGENTS.md）
├─ tests/unit  tests/e2e        # 快速单测（<10s）/ 端到端回归（<30s）
├─ CHANGELOG.md
└─ .agents/                     # 本仓库自己的契约落盘件（project.py / VERSION / .source）
```

**两层边界**：技能本体（本仓库）负责实现与升级；项目契约（`AGENTS.md` + `.agents/project.py` + 执法包落盘件，纯 Python 项目共 8 个文件，Node 项目多 1 个）安装进具体项目。执行逻辑永不复制进项目。

## 安装 / 使用

把技能装进宿主，任选一种（都不需要联网装依赖，纯标准库）：

- **克隆（推荐，可用 `tsc update` 自升级）**：
  `git clone https://github.com/xlzxld/TSC "<宿主技能目录>/tsc"`
  （宿主技能目录举例：`~/.workbuddy/skills/`、`~/.claude/skills/`——按你所在平台的实际路径放。）
- **拷贝**：直接把这个仓库（或只把 `skills/tsc/`）拷进宿主技能目录；非 git 副本无法 `tsc update`，升级靠重新拷贝。
- **宿主插件市场**：如果宿主支持"添加插件市场"，填本仓库地址也行（本仓库不含平台私有清单，能否识别取决于宿主）。

装好后对 AI 说一句话（无需敲命令）：

| 你说 | AI 做 |
| --- | --- |
| **"接入契约"** | 探测项目 → `install --dry-run` 预览 → 确认后写入契约 + 执法包 → 填 §2 → `verify` + `doctor` |
| **"更新 TSC"** | 只升级技能本体（git 安装副本自动 pull；非 git 副本提示重新拷贝） |
| **"更新契约" / "同步契约"** | 把当前已安装技能同步进项目（`sync`，只认当前本体，不联网、不看项目 `.source`） |
| **"升级 TSC，并同步当前项目"** | 一句话完整升级链：升本体 → 同步项目 → 门禁 → 汇报版本变化 |
| **"回滚契约"** | `rollback`：撤销最近一次 install/sync 的写入 |
| **"契约状态"** / `/tsc` | `status` + `doctor`（ready / not-ready 结论） |
| **"体检"** | 只读审计，输出问题清单后停下等确认 |

## 三层门禁与"自动拦截"

| 层 | 谁触发 | 覆盖 |
| --- | --- | --- |
| **本地 git 钩子** | 你自己 `git commit` | 暂存内容（密钥 + 结构门禁）；由 `install_hook.py` 安装，跨平台 |
| **CI（`gate.yml`）** | push / PR | 全历史密钥扫描 + 结构门禁 + 聚合门禁（按 `.agents/project.py` 逐条跑） |
| **宿主 hook（可选）** | AI 改完文件 | 任何支持"工具调用后跑命令"的宿主都能接 `structure_guard.py --from-hook`（stdin 收 JSON，退出码 2 = 拦住）。本技能**不预设**任何平台的 hook 清单，需要就去宿主侧配 |

三层相互独立，装哪层算哪层；本地钩子缺失时 CI 仍兜底。

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
SK=<技能根，即 skills/tsc 所在目录>
python3 "$SK/scripts/tsc.py" status      --project <项目根>   # 状态（--json 机器可读）
python3 "$SK/scripts/tsc.py" install     --project <项目根>   # 首次接入（外部 AGENTS.md 接管加 --force）
python3 "$SK/scripts/tsc.py" sync        --project <项目根>   # 项目契约同步到当前本体
python3 "$SK/scripts/tsc.py" update                           # 只升级本体（git pull --ff-only，带超时）
python3 "$SK/scripts/tsc.py" verify      --project <项目根>   # 聚合门禁（每条命令带超时）
python3 "$SK/scripts/tsc.py" check-config --project <项目根>  # §2 与 project.py 同源校验
python3 "$SK/scripts/tsc.py" doctor      --project <项目根>   # 只读诊断：ready / not-ready
python3 "$SK/scripts/tsc.py" rollback    --project <项目根>   # 撤销最近一次 install/sync
```

退出码：`0` 成功/已是最新；`1` 需人工处理（§2 结构变更、外部 AGENTS.md 未接管、§2 与 project.py 不一致）；`2` IO/权限错误；`3` 状态非法；`124` 门禁命令超时。

**解释器写法**：`python3` 在部分 Windows 上不存在。门禁命令里写 `python3` 或 `python` 都可以——`verify` 执行前会检查该名字是否解析得到，解析不到就自动改用当前解释器并明确告警；CI 内联壳同口径。命令源（§2 与 project.py）因此可以保持静态字符串，同源校验不受影响。

## 维护本仓库（发版）

1. 改 `skills/tsc/templates/AGENTS.md`（母版）与 `skills/tsc/scripts/`，bump `skills/tsc/VERSION`（版本发布唯一真源）。
2. 在仓库根跑 `python3 skills/tsc/scripts/tsc.py sync --project .` 自举（生成 gitignore 掉的 `.agents/VERSION`/`.source`，根 AGENTS.md 与模板校验零漂移）。
3. `CHANGELOG.md` 顶部记一笔。
4. 门禁：`wc -l AGENTS.md` < 80；`python3 skills/tsc/scripts/tsc.py verify` 退出码 0（含 unit + e2e）。
5. 提交走 Conventional Commits；标签用扁平名（`v4.0.0`）。

## 平台支持（如实记录）

- **macOS**：v4.0.0 发布平台，已实测。
- **Linux**：标准库实现，无平台专属调用；CI（`gate.yml`）跑在 `ubuntu-latest`。
- **Windows**：v3.x 实测过核心同步逻辑；v4.0.0 重组后已修掉一批 Windows 专属问题（测试夹具里的 POSIX 命令、CI 壳与 pre-commit 模板写死 `python3`、`doctor` 自举误报、worktree/submodule 定位），本机实测 `verify` 退出码 0。**尚缺**真正的多平台 CI 矩阵——见下方"已知缺口"。

## 已知缺口（诚实登记）

- 本仓库自身不跑 CI（刻意如此：母版不部署自己的执法包，避免出现第二份真身）。代价是**只在 Windows 暴露的问题拦不住**——A-02 那批测试缺陷就是这样漏进主干的。补一个独立命名的多平台工作流（`ubuntu` + `windows` + `macos`）是下一步，不与托管的 `gate.yml` 冲突。
- `tsc.py` 单文件约 1500 行，聚合了 CLI、所有权判定、配置比对、原子写、进程管理。当前取舍是"零依赖单文件最好分发"；若长期迭代，值得按数据模型 / 执行引擎 / 文件系统接口分层。
- Windows 超时终止依赖外部 `taskkill.exe`（不可用时退回单进程终止，超时结论不受影响）。理论上可换 Windows 原生 Job Object 做到零残留，属优化而非缺陷。
