---
name: tsc
description: |
  TSC 契约技能：把一套 AI 行为契约（AGENTS.md + 门禁）接入任意项目，并负责
  分发、同步、升级与回滚。触发词：tsc、接入契约、更新契约、同步契约、更新 TSC、
  升级 TSC、契约状态、TSC 体检、契约门禁、装结构门禁。
  当用户提到"安装/接入/更新/同步契约""更新 TSC""契约状态""tsc"时使用本技能。
metadata:
  display_name: "TSC 契约"
  display_name_en: "TSC Contract"
  upstream: "https://github.com/xlzxld/TSC"
---

# TSC 契约技能

**两层边界**（不要混）：

- **本体（Skill/Plugin）**：本技能所在的插件目录。执行逻辑都在这里：`scripts/tsc.py`（唯一 CLI）、`scripts/structure_guard.py`、`scripts/bracket_lint.py`、`scripts/install_hook.py`；项目落盘模板在 `templates/`。下文用 `<插件根>` 指代本文件所在的插件目录（SKILL.md 的上两级）。
- **项目契约**：安装到具体项目里的 `AGENTS.md` + `.agents/project.py` + 执法包落盘件。项目里**绝不**复制执行逻辑。

## 一句话 → 动作（用户永远不需要敲命令）

| 用户说 | 你做（底层命令仅供你执行，不要贴给用户当作业） |
| --- | --- |
| "TSC 状态" / "契约状态" | `python3 <插件根>/scripts/tsc.py status --project <项目根>`（加 `--json` 可拿机器可读版） |
| **"接入契约"** / "安装契约" | ① `install --dry-run` 报给用户看 → 确认后去掉 `--dry-run` 真跑 → ② 按 `references/BOOTSTRAP.md` 探测项目、填 §2 与 `.agents/project.py` → ③ `check-config` + `verify` + `doctor` |
| **"更新契约"** / "同步契约" | `sync --project <项目根>`（先 `--dry-run` 预览；只从**当前已安装本体**取内容，不联网、不读项目 `.source`） |
| **"更新 TSC"** / "升级 TSC 本体" | `tsc.py update`（git pull 本体；非 git 安装副本会提示走宿主插件市场更新）。只动本体，不碰项目 |
| **"升级 TSC，并同步当前项目"** | 先 `update`，再 `sync --project <项目根>`，再 `check-config` + `verify`，汇报版本变化与门禁退出码 |
| "TSC 体检" / "audit" | 只读审计：读 `references/AUDIT-SPEC.md` 按其规则执行，输出问题清单后**立即停**，严禁修改 |
| "回滚契约" | `tsc.py rollback --project <项目根>`（撤销最近一次 install/sync 的写入） |
| "结构体检" | `python3 <插件根>/scripts/structure_guard.py <文件/目录>`（只读） |
| "装结构门禁" | `python3 <插件根>/scripts/install_hook.py --repo <项目根>`（装 pre-commit，装/卸幂等） |

`python3` 不存在时用 `python`（Windows 常见）。**汇报必须附实际命令与退出码**，不要说"应该没问题"。

## 所有权边界（最优先的安全规则）

- 项目 `AGENTS.md` 带 `<!-- tsc-managed-contract:v4 -->` 标记 = TSC 托管，可 install/sync。
- **没有标记 = 外部文档，默认只读**：`sync`/`install` 会拒绝并输出冲突摘要；只有用户明确确认后 `install --force` 才接管。
- 项目里带 `tsc-managed` 标记的执法包文件随本体更新；被项目改掉标记的文件永不覆盖。
- 任何删除都先问用户（rollback 删除的仅限上次 install/sync 新建的文件）。

## 退出码

| 码 | 含义 | 你要做的 |
| --- | --- | --- |
| 0 | 成功 / 已是最新 | 报结论 |
| 1 | 需人工处理（§2 结构变更 / 外部 AGENTS.md 未接管 / §2 与 project.py 不一致） | 停下转述脚本列出的差异，等用户决定 |
| 2 | IO / 编码 / 权限错误 | 停下原样转述 |
| 3 | 状态非法（缺 §2、门禁全未配置、上游无效、无可回滚记录） | 按提示修复 |
| 124 | 门禁命令超时被终止 | 转述；确需更久用 `--timeout` 或 project.py 的 `GATE_TIMEOUTS` 放宽 |

## 写完代码后的自动动作（不需要用户开口）

1. 改完文件 → 跑 `verify`（未验证不交付）。
2. `verify` 过了 → 跑 `check-config`（§2 与 project.py 没跑偏）。
3. 提交前 `verify` 必须退出码 0，否则不许提交、不许说"已完成"。

唯一要先问用户的：`install` / `sync` 首次写入（先 `--dry-run` 给用户看）。`verify`/`status`/`doctor` 只读，直接跑。

新装项目 §2 全是 `[自动填充]`、`.agents/project.py` 四条命令全 `None`——两处都要填成本项目真实取值（按 `references/BOOTSTRAP.md` 探测），否则 `verify` 退出码 3（未配置不是通过）。填完代跑 `check-config` 确认同源。

## 深度参考（按需读，不常驻）

- `references/AUDIT-SPEC.md`：体检细则（说"体检"时）。
- `references/BOOTSTRAP.md`：项目探测与 §2 填充流程（接入契约时）。
- 结构门禁退出码：0=通过；1=代码结构问题；2=工具自身故障（告警放行）；3=配置非法；hook 模式 fail-open。行内豁免注释 `guard:skip`。
