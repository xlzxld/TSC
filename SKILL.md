---
name: tsc
description: |
  项目 AI 行为契约（AGENTS.md + .agents/）的分发、同步与门禁技能。
  触发词：tsc、/tsc、接入契约、同步契约、契约体检、契约门禁、tsc verify。
  用于往一个项目里接入或更新契约文件、运行聚合门禁、按契约执行体检与修复流程。
  当用户提到"接入契约""跑契约门禁""契约体检""tsc"时使用本技能。
agent_created: true
version: 3.1.2
display_name: "TSC 契约"
display_name_en: "TSC Contract"
description_zh: "把 AI 行为契约一键接入项目，并提供同步与聚合门禁。"
description_en: "Install, sync and enforce the AI coding contract in any project."
visibility: "public"
---

# TSC 契约技能

本技能把一套 AI 行为契约分发进项目。**执行逻辑全部留在这里（技能目录），项目里只落"必须躺在项目里"的东西**：

| 落到项目 | 为什么必须进项目 |
| --- | --- |
| 根目录 `AGENTS.md` | 各平台认"项目根目录自动读"；放技能目录里 AI 不会加载 |
| `.agents/project.py` | 本项目自己的门禁命令，跨项目不通用 |
| `.agents/VERSION`、`.agents/.source` | 版本号与上游位置，几百字节 |
| `.pre-commit-config.yaml`、`commitlint.config.js`、`.github/workflows/gate.yml` | git 钩子与 CI **只能读项目自己的文件**，够不着技能目录 |

**不进项目**（留在技能目录，由你直接调用）：`tsc.py`、`AUDIT-SPEC.md`、`BOOTSTRAP.md`、`verify.ps1` / `verify.sh`、`test/`、`enforcement/` 模板原件。

- **技能目录**（即本文件所在目录）就是"上游"。下文用 `<SKILL_DIR>` 指代它。
- **核心脚本**：`<SKILL_DIR>/.agents/tsc.py`，零第三方依赖（Windows 已实测；macOS / Linux 仅用标准库、无平台专属调用，待实测）。**它常驻技能目录，不复制进项目**。

## 一、怎么触发：用户说一句话，其余全是你的事

用户只说一句话，**永远不需要敲命令**。下面左列是人话，右列是你的动作。更关键的是：**大部分动作不需要用户开口**——见 §二。

| 用户可能说 | 你执行 |
| --- | --- |
| "tsc"、"契约状态"、"现在什么情况" | `status --project "<目标项目根>"` |
| **"接入契约"**（或"上契约""把这个项目接上契约"） | 先 `install ... --dry-run` 报给用户看 → 确认后去掉 `--dry-run` 再跑 |
| "同步契约"、"契约更新了拉一下" | 先 `sync ... --dry-run` 报给用户看 → 确认后去掉 `--dry-run` 再跑 |
| "体检"、"audit" | 读 `<SKILL_DIR>/.agents/AUDIT-SPEC.md`，按其铁律执行（**只读**，输出问题清单后立即停） |
| "修复 X" | 读 `<SKILL_DIR>/.agents/AUDIT-SPEC.md` 定级表 + 项目 `AGENTS.md` §3 红线，按"先跑基线 → 最小改动 → 回归 → 门禁 → 原子提交"执行 |
| "适配"、"初始化规范" | 读 `<SKILL_DIR>/.agents/BOOTSTRAP.md`，按其模式 A/B/C 执行 |

展开后的底层命令（**脚本在技能目录，一律用 `--project` 指目标项目**；**仅供你内部执行，不要贴给用户当任务**）：

```bash
python3 "<SKILL_DIR>/.agents/tsc.py" status       --project "<目标项目根>"
python3 "<SKILL_DIR>/.agents/tsc.py" install      --from "<SKILL_DIR>" --project "<目标项目根>"
python3 "<SKILL_DIR>/.agents/tsc.py" sync         --from "<SKILL_DIR>" --project "<目标项目根>"
python3 "<SKILL_DIR>/.agents/tsc.py" verify       --project "<目标项目根>"
python3 "<SKILL_DIR>/.agents/tsc.py" check-config --project "<目标项目根>"
```

省略 `--project` 时取当前工作目录，所以"cd 到项目里再跑"同样成立。`AUDIT-SPEC.md` / `BOOTSTRAP.md` 也一样从 `<SKILL_DIR>` 读。

`<目标项目根>` 默认取当前工作目录。Windows 下把 `python3` 写成 `python`（或直接用 `.agents/verify.ps1`）；这层差异由你处理，不要推给用户去记。

**汇报时**只给结论与证据（命令 + 退出码），不要给出"请你执行以下命令"的作业。

## 二、自动执行：这些动作不需要用户开口

用户的原话是"跑门禁什么的应该由 AI 自动判断自动执行"。所以下列时机**你主动跑，不要问、不要等**：

| 时机 | 自动执行 |
| --- | --- |
| 任何一次写完代码 / 改完文件之后 | `verify` —— 这就是 R-0.1"未验证不交付"的落地方式 |
| 跑完 `verify` 之后 | `check-config` —— 确认 §2 与 `project.py` 没跑偏 |
| 准备提交之前 | `verify` 必须退出码 0，否则不许提交、不许说"已完成" |
| 用户说"体检"给完问题清单、开始修之后 | 每个问题修完立刻 `verify`，不要攒到最后一起跑 |
| 用户说"接入契约"之后 | 自动补跑一次 `check-config` |
| 拿不准项目是否已接入时 | 先 `status` 再决定，不要瞎猜 |

**唯一需要先问用户的**：`install` / `sync` 的首次写入（它们会改动文件，所以先 `--dry-run` 给用户看）。

`verify` 不需要问。它只读不写，跑就是了。

> 例外：`project.py` 四条命令全是 `None` 时，`verify` 会全程 skip 并打印"全绿"。这不算通过——
> 你要显式告诉用户"门禁没配，这是假绿"，而不是当成验收通过。

## 三、动手前先确认三件事

1. **项目根对不对**——改变的是哪个项目，别默认到技能目录自己身上。
2. **写入类命令先 `--dry-run`**：`sync` 与 `install` 首次执行时一律先给用户看将发生什么，得到确认后再真跑。
3. **退出码要原样回报**——脚本的退出码含义：

| 码 | 含义 | 你要做的 |
| --- | --- | --- |
| 0 | 成功 / 已是最新 | 报结论 |
| 1 | §2 结构有变更，需人工合并 | **停下**，把脚本列出的缺失字段转告用户，等他补完再重跑 |
| 2 | IO / 编码 / 权限错误 | 停下，原样转述错误 |
| 3 | 状态非法（缺 §2、缺 VERSION、找不到上游） | 停下，按提示修复 |

## 四、硬约束（来自契约本身，不可豁免）

- **绝不覆盖 `AGENTS.md` 的 §2**。§2 是项目自己的门禁配置，`sync` 只替换 §2 以外的内容。脚本已内建此规则；**不要**用整文件覆盖的方式"绕过"它。
- **绝不自动删除文件**。脚本只做移动与提示；任何删除都必须先向用户确认，并附零引用检索证据与回滚方式。
- **不要手工编辑 `<SKILL_DIR>/.agents/` 下的上游文件**（`tsc.py`、`AUDIT-SPEC.md`、`BOOTSTRAP.md`、`enforcement/`、`test/`、`verify.ps1` / `verify.sh`、`project.example.py`、`VERSION`），改上游再同步。项目里已不再有这些文件的副本。
- **`.agents/project.py` 是项目自己的**，上游永不覆盖；缺它时 `verify` 会退出 3。
- 汇报门禁结果必须附**实际执行的命令与退出码**，禁止用"应该没问题"这类措辞。
- 涉及新增依赖、破坏性 git 操作、改公共配置时，**先停下问用户**。

## 五、首次接入后要提醒用户的一件事

新装项目的 `AGENTS.md` §2 取值列全是 `[自动填充]` 占位（不会继承母版仓库自己的取值），`.agents/project.py` 四条命令也都是 `None`——**两处都要填成本项目真实取值**，否则门禁会全程 skip 而给出"全绿"的假结论、`check-config` 也会报不一致。填完由你代跑一次 `check-config` 确认同源——同样不要让用户自己去敲。

## 六、执法包是默认安装项

`install` 会把执法包的**三份模板落到生效位置**（模板原件留在 `<SKILL_DIR>/.agents/enforcement/`，不复制进项目）：

| 模板 | 落到 | 作用 |
| --- | --- | --- |
| `gate.yml` | 项目的 `.github/workflows/gate.yml` | PR / 主干 push 上的 CI 门禁 |
| `.pre-commit-config.yaml` | 项目根 | gitleaks 密钥扫描 + commitlint |
| `commitlint.config.js` | 项目根 | Conventional Commits 规则 |

落盘后**你要提醒用户两件只能由人做的事**（脚本做不了）：

1. **激活本地钩子**（要先装依赖，否则钩子会拦死提交）：
   ```bash
   pip install pre-commit
   npm i -D @commitlint/cli @commitlint/config-conventional
   pre-commit install
   pre-commit install --hook-type commit-msg
   ```
   ⚠️ 本地钩子不是软开关：激活后依赖缺失会让 `git commit` 直接失败。用户不想被拦就**别执行**那两条 `install`，只留 CI 那层。
2. **开分支保护**：GitHub → Settings → Branches，按 `<SKILL_DIR>/.agents/enforcement/README.md` 的三步勾选，
   其中"Branch name pattern"要与项目 `AGENTS.md` §2 的「主干分支」取值一致。

`gate.yml` 首次生成时按 §2 的「主干分支」取值自动填好 `branches:`；改过主干名后要重跑 `install` 才会更新这一行。

**三层各拦什么**（被问到时要能说清）：本地钩子只扫**本次暂存**的内容，CI 那一步才是**全历史**密钥扫描。所以"本地绿了"不等于仓库历史干净。

**归属规则**：三份落盘件都带 `tsc-managed` 标记行。带标记 = 技能托管，`install` / `sync` 时随上游模板自动覆盖更新；用户删掉标记行再改内容 = 项目接管，技能永不覆盖只提示。被问到"为什么我的 gate.yml 被改回去了"时，答案就是标记还在——要自己维护就删标记行。
