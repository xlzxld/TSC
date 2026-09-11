#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tsc —— 契约分发与门禁的唯一核心脚本（常驻技能目录）。

用法（**脚本留在技能目录，用 --project 指定目标项目**）：
    python3 <技能目录>/.agents/tsc.py status       --project <项目根>
    python3 <技能目录>/.agents/tsc.py install      --from <技能目录> --project <项目根>
    python3 <技能目录>/.agents/tsc.py sync         --from <技能目录> --project <项目根>
    python3 <技能目录>/.agents/tsc.py verify       --project <项目根>
    python3 <技能目录>/.agents/tsc.py check-config --project <项目根>

    `--project` 省略时取当前工作目录，因此"cd 到项目里再跑"也成立。

通用参数：
    --from <路径>   上游来源（本地路径；目录需含 AGENTS.md、VERSION、.agents/）
    --project <路径> 目标项目根（默认当前目录）
    --dry-run       只报告将发生的变化，不写任何文件

退出码：
    0  成功 / 已是最新
    1  需要人工合并（§2 结构有变更）或校验不一致
    2  IO / 编码 / 权限错误
    3  状态非法（缺 §2、缺 VERSION、找不到上游）

设计约束：
    - 零第三方依赖，仅用标准库（Windows 已实测；macOS / Linux 待实测）。
    - 所有文本读写强制 UTF-8 与 LF，避免 Windows 默认 CRLF 破坏行数门禁口径。
    - 不联网、不调用 git；上游来源只接受本地路径（技能目录本身就是上游）。
    - 绝不自动删除文件；旧结构只做"移动 + 提示"。
    - 执法包（enforcement/）默认随 install 落盘；已存在且被项目改过的文件只提示、不覆盖。
    - **不往项目里复制执行逻辑**（本脚本、AUDIT-SPEC、BOOTSTRAP、verify.*、test/），
      它们常驻技能目录；项目内只留契约（AGENTS.md）、项目配置（project.py）与生效件。
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_MERGE = 1
EXIT_IO = 2
EXIT_STATE = 3

AGENTS_MD = "AGENTS.md"
AGENTS_DIR = ".agents"
VERSION_FILE = "VERSION"
SOURCE_FILE = ".source"
PROJECT_FILE = "project.py"
PROJECT_EXAMPLE = "project.example.py"
SECTION2_HEADING = "## 2."

# 执法包模板 → 落地位置（默认随 install 一起部署）
ENFORCE_DIR = "enforcement"
ENFORCE_DEPLOY = {
    "enforcement/gate.yml": ".github/workflows/gate.yml",
    "enforcement/.pre-commit-config.yaml": ".pre-commit-config.yaml",
    "enforcement/commitlint.config.js": "commitlint.config.js",
}
# 归属标记：模板里带此标记的落盘件视为"技能托管"，上游模板更新时自动覆盖；
# 文件里没有此标记且内容对不上模板 → 视为用户已接管，永不覆盖。
MANAGED_MARKER = "tsc-managed"

# --------------------------------------------------------------------------- #
# 分发策略：项目里只放"必须躺在项目里"的东西，执行逻辑一律留在技能目录
#
# 不进项目（留在技能/上游目录，由 agent 直接调用）：
#   tsc.py、AUDIT-SPEC.md、BOOTSTRAP.md、verify.ps1 / verify.sh、test/、enforcement/ 模板原件
# 理由：技能已装在 agent 平台上，这些逻辑随时可调；复制进项目纯属冗余。
#
# 必须进项目：
#   AGENTS.md       —— 各平台认"项目根目录自动读"，放技能目录里 AI 不会加载
#   project.py      —— 本项目自己的门禁命令，跨项目不通用
#   .source         —— 记录上游位置，供项目内调用
#   enforcement 落盘件 —— git 钩子 / CI 只能读项目自己的文件，够不着技能目录
# --------------------------------------------------------------------------- #
SKILL_ONLY_ENTRIES = [
    "tsc.py",
    "AUDIT-SPEC.md",
    "BOOTSTRAP.md",
    "verify.ps1",
    "verify.sh",
    "test",
    "project.example.py",
    ENFORCE_DIR,
]


# --------------------------------------------------------------------------- #
# 输出：Windows 控制台默认 GBK，中文会直接抛 UnicodeEncodeError，必须强制 UTF-8
# --------------------------------------------------------------------------- #
def _init_stdout():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def say(msg=""):
    print(msg)


def warn(msg):
    print(msg, file=sys.stderr)


# --------------------------------------------------------------------------- #
# 文本读写：统一 UTF-8 + LF
# --------------------------------------------------------------------------- #
def read_text(path):
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read().replace("\r\n", "\n").replace("\r", "\n")


def write_text_atomic(path, text, dry_run=False):
    """先写临时文件再替换，避免留下半成品。"""
    if dry_run:
        return
    path = Path(path)
    tmp = path.with_name(path.name + ".tsc-tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(tmp, path)


def write_version(path, version, dry_run=False):
    write_text_atomic(path, version.strip() + "\n", dry_run)


# --------------------------------------------------------------------------- #
# §2 项目区：锚点切分与结构校验
# --------------------------------------------------------------------------- #
def section2_span(text):
    """返回 §2 章节的 (起始行号, 结束行号)；找不到返回 None。"""
    lines = text.split("\n")
    start = None
    for i, line in enumerate(lines):
        if line.startswith(SECTION2_HEADING):
            start = i
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    return start, end


def section2_text(text):
    span = section2_span(text)
    if span is None:
        return None
    start, end = span
    return "\n".join(text.split("\n")[start:end])


def section2_signature(block):
    """提取 §2 结构指纹：表格列数 + 各行首标签。用于判断上游是否改了结构。"""
    columns = []
    labels = []
    for line in block.split("\n"):
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if cells and set("".join(cells)) <= set("-: "):
            continue  # 表头分隔行
        if not columns:
            columns = cells
            continue
        labels.append(cells[0])
    return columns, labels


def compose_agents_md(upstream_text, project_text):
    """用上游模板重建 AGENTS.md，但保留项目现有的 §2。"""
    start, end = section2_span(upstream_text)
    lines = upstream_text.split("\n")
    keep = section2_text(project_text)
    merged = lines[:start] + keep.split("\n") + lines[end:]
    return "\n".join(merged)


# --------------------------------------------------------------------------- #
# 上游定位
# --------------------------------------------------------------------------- #
def script_dir():
    return Path(__file__).resolve().parent


def normalize_path_arg(value):
    """兼容 Git Bash / MSYS 风格的 /c/Users/... 路径。

    Windows 上从 Git Bash 传 --project /c/foo 会被 Python 解析成 C:\\c\\foo，
    这里统一还原成 C:/foo，避免"路径看着对、实际找不到"的假故障。
    """
    text = str(value)
    if (
        os.name == "nt"
        and len(text) > 3
        and text[0] == "/"
        and text[1].isalpha()
        and text[2] == "/"
    ):
        return text[1].upper() + ":" + text[2:]
    return text


def find_upstream(explicit, proj_root):
    """按 显式 --from > 项目 .agents/.source > 脚本自身所在仓库 的顺序定位上游。

    .source 记录的路径失效（技能目录搬家）时回退到脚本所在仓库并提示，
    存量项目仍可继续 sync/status；install/sync 成功后会顺手修正记录（见 do_apply）。
    """
    if explicit:
        return Path(normalize_path_arg(explicit)).expanduser().resolve()
    source_file = Path(proj_root) / AGENTS_DIR / SOURCE_FILE
    if source_file.is_file():
        recorded = read_text(source_file).strip()
        if recorded:
            candidate = Path(recorded).expanduser().resolve()
            if validate_upstream(candidate):
                # 校验有缺失项 → 记录已失效，回退到脚本所在仓库
                warn("记录的上游已失效（技能目录可能搬过家）：%s" % candidate)
                warn("本次回退到脚本所在仓库继续；install/sync 会顺手把 .source 修正为实际使用的上游。")
                return script_dir().parent
            return candidate
    return script_dir().parent  # 技能/母版自举：脚本上一级即上游根


def source_record_current(proj_root, upstream):
    """项目 .agents/.source 是否已记录为当前上游。

    缺失、空文件、死路径、指向别的有效上游（显式 --from 换过源）都算"未记录当前"，
    do_apply 会把它重写为本次实际使用的上游——否则下次裸 sync 会静默回到旧上游。
    """
    source_file = Path(proj_root) / AGENTS_DIR / SOURCE_FILE
    if not source_file.is_file():
        return False
    return read_text(source_file).strip() == str(upstream)


def validate_upstream(root):
    return [
        name
        for name in (AGENTS_MD, VERSION_FILE, AGENTS_DIR)
        if not (root / name).exists()
    ]


def upstream_version(root):
    vf = root / VERSION_FILE
    if not vf.is_file():
        return None
    return read_text(vf).strip()


def local_version(proj_root):
    vf = Path(proj_root) / AGENTS_DIR / VERSION_FILE
    if not vf.is_file():
        return None
    return read_text(vf).strip()


# --------------------------------------------------------------------------- #
# 旧结构迁移（只移动，不删除）
# --------------------------------------------------------------------------- #
# 旧版契约把 AUDIT-SPEC.md / BOOTSTRAP.md / enforcement/ / test/ 散在项目根目录。
# 其中 enforcement / test 是通用名，项目自己的同名目录绝不能误搬（v3.1.2 修复）：
#   1) 项目根必须先有 AGENTS.md（确曾部署过契约）才谈得上"旧结构"；
#   2) 通用名目录必须带契约内容签名（旧版执法包 / 测试材料特有的文件）才认。
LEGACY_FILE_ENTRIES = ["AUDIT-SPEC.md", "BOOTSTRAP.md"]
LEGACY_DIR_SIGNATURES = {
    "enforcement": ("gate.yml", "Makefile"),
    "test": (
        "test_tsc.py",
        "EVAL-SET.md",
        "TEST-MANUAL.md",
        "TEST-ANSWERS.md",
        "ACCEPTANCE.md",
    ),
}


def detect_legacy(proj_root):
    proj_root = Path(proj_root)
    if not (proj_root / AGENTS_MD).is_file():
        return []  # 从未部署过契约的项目没有"旧结构"可言
    found = [n for n in LEGACY_FILE_ENTRIES if (proj_root / n).is_file()]
    for name, signatures in LEGACY_DIR_SIGNATURES.items():
        subdir = proj_root / name
        if subdir.is_dir() and any((subdir / s).exists() for s in signatures):
            found.append(name)
    return found


def detect_skill_only_leftovers(proj_root):
    """项目 .agents/ 里残留的执行逻辑（现已统一放技能目录）。只用于提示，不删除。

    扫描目标本身就是上游/技能目录时返回空——那里的逻辑是正本，不是冗余。
    """
    proj_root = Path(proj_root)
    try:
        if proj_root.resolve() == script_dir().parent.resolve():
            return []
    except OSError:
        pass
    agents_dir = proj_root / AGENTS_DIR
    return [n for n in SKILL_ONLY_ENTRIES if (agents_dir / n).exists()]


def migrate_legacy(proj_root, dry_run):
    """把根目录的旧布局搬进 .agents/。返回 (已移动, 建议人工处理)。"""
    proj_root = Path(proj_root)
    agents_dir = proj_root / AGENTS_DIR
    moved, leftover = [], []
    for name in detect_legacy(proj_root):
        src = proj_root / name
        dst = agents_dir / name
        if dst.exists():
            leftover.append(src)
            continue
        moved.append((src, dst))
        if not dry_run:
            agents_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
    return moved, leftover


# --------------------------------------------------------------------------- #
# 同步主流程
# --------------------------------------------------------------------------- #
def collect_payload(upstream):
    """列出需要分发到项目的文件：键为相对项目根的路径，值为上游源文件。

    **只分发"必须躺在项目里"的文件**（见 SKILL_ONLY_ENTRIES 上方的说明）：
    版本号一个。执行逻辑（tsc.py / AUDIT-SPEC / BOOTSTRAP / verify.* / test / 执法包模板原件）
    一律留在技能目录，不往项目里复制。

    注意：**不包含根 AGENTS.md**。它需要与项目现有 §2 合成后再写，
    由 do_apply 单独处理；若也放进这里，会被原始上游文件覆盖掉 §2 定制。
    """
    items = [(Path(AGENTS_DIR) / VERSION_FILE, upstream / VERSION_FILE)]
    return items


PLACEHOLDER = "[自动填充]"


def section2_to_placeholder(text):
    """把 §2 表格的「命令 / 取值」列整体替换为占位符（结构与验证条件列保持原样）。

    用于全新 install：目标项目还没探测过环境，绝不能继承母版仓库自己的取值。
    母版 §2 既是本仓库的真实配置、又是分发模板，本函数在分发时把取值抹成占位，
    保持"契约只有一个真身"，不引入第二份 §2 模板。
    """
    span = section2_span(text)
    if span is None:
        return text
    lines = text.split("\n")
    start, end = span
    out = []
    for i, line in enumerate(lines):
        if start <= i < end:
            stripped = line.strip()
            if stripped.startswith("|"):
                cells = [c.strip() for c in stripped.strip("|").split("|")]
                if cells and set("".join(cells)) <= set("-: "):
                    out.append(line)  # 表头分隔行
                    continue
                if len(cells) >= 2 and cells[0] != "项":
                    cells[1] = PLACEHOLDER
                    out.append("| " + " | ".join(cells) + " |")
                    continue
        out.append(line)
    return "\n".join(out)


def section2_value(block, row_prefix):
    """从 §2 表格取某一行「命令 / 取值」列（第 2 列）的值。找不到返回 None。"""
    if not block:
        return None
    for line in block.split("\n"):
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 2 or set("".join(cells)) <= set("-: "):
            continue
        if cells[0].startswith(row_prefix):
            return cells[1]
    return None


def _enforce_actions(proj_root, upstream, merged_agents_text):
    """算出执法包落盘动作，不写任何文件（判定单源，供部署与早退检查共用）。

    归属规则（MANAGED_MARKER = "tsc-managed"）：
    - 项目文件带标记 → 技能托管：以上游模板为准，内容不同就更新；
    - 不带标记但正文与模板一致（忽略标记行与 gate.yml 分支名）→ 旧版部署
      的文件，一次性升级为带标记的托管版；
    - 不带标记且正文不同 → 项目已接管，永不覆盖，只提示。
    返回 (新部署, 已更新, 跳过)：
      部署/更新为 (相对路径, 内容) 列表，跳过为 (相对路径, 原因) 列表。
    """
    proj_root = Path(proj_root)
    src_root = Path(upstream) / AGENTS_DIR
    try:
        if proj_root.resolve() == Path(upstream).resolve():
            # 母版/技能目录自举：模板原件已在 .agents/enforcement/，
            # 不往自己根目录铺生效件（保持上游纯净）
            return [], [], []
    except OSError:
        pass
    main_branch = section2_value(section2_text(merged_agents_text), "主干分支")
    if main_branch and PLACEHOLDER in main_branch:
        main_branch = None  # §2 还是占位符（未适配）→ gate.yml 保持模板默认 [main]
    deploy, update, skip = [], [], []

    def normalize(text):
        # 去掉归属标记行，行尾统一，用于"正文是否一致"的比较
        lines = [ln for ln in text.splitlines() if MANAGED_MARKER not in ln]
        return "\n".join(lines).rstrip("\n")

    def debranch(text):
        # 把技能自动部署的分支名归一回模板默认值，供比较用；
        # 用户手改的其他分支名不会被归一，仍判为"内容不同"。
        if main_branch:
            return text.replace("branches: [%s]" % main_branch, "branches: [main]")
        return text

    for rel_src, rel_dst in ENFORCE_DEPLOY.items():
        src = src_root / rel_src
        if not src.is_file():
            continue
        dst = proj_root / rel_dst
        template = read_text(src)
        content = template
        if rel_src.endswith("gate.yml") and main_branch:
            content = content.replace("branches: [main]", "branches: [%s]" % main_branch)

        if not dst.is_file():
            deploy.append((rel_dst, content))
            continue

        existing = read_text(dst)
        if MANAGED_MARKER in existing:
            # 技能托管：上游模板说了算
            if existing != content:
                update.append((rel_dst, content))
            continue

        # 旧版部署的一次性迁移：正文一致（忽略标记行与分支名）→ 升级为托管版
        if normalize(debranch(existing)) == normalize(template):
            update.append((rel_dst, content))
            continue

        skip.append((rel_dst, "内容已被项目改过"))

    return deploy, update, skip


def enforcement_pending(proj_root, upstream, merged_agents_text):
    """同版本早退判定用：执法包还有没有待落盘的动作（新部署或更新）。"""
    deploy, update, _ = _enforce_actions(proj_root, upstream, merged_agents_text)
    return bool(deploy or update)


def deploy_enforcement(proj_root, upstream, merged_agents_text, dry_run):
    """把执法包模板落到生效位置（gate.yml 的主干分支名跟随 §2）。

    dry_run 只报告不写盘。返回 (新部署, 已更新, 跳过) 三个名字列表。
    """
    deploy, update, skip = _enforce_actions(proj_root, upstream, merged_agents_text)
    if not dry_run:
        for rel_dst, content in deploy + update:
            dst = Path(proj_root) / rel_dst
            dst.parent.mkdir(parents=True, exist_ok=True)
            write_text_atomic(dst, content)
    return (
        [name for name, _ in deploy],
        [name for name, _ in update],
        skip,
    )


def do_apply(proj_root, upstream, dry_run, force):
    """sync / install 共用的落地逻辑。返回退出码。"""
    proj_root = Path(proj_root)
    upstream_agents = upstream / AGENTS_MD
    project_agents = proj_root / AGENTS_MD

    up_text = read_text(upstream_agents)
    if section2_span(up_text) is None:
        warn("上游 AGENTS.md 找不到 §2 章节，拒绝继续（防止整文件覆盖）。")
        return EXIT_STATE

    # 1) 先合并出目标 AGENTS.md：同版本的早退判定也要用它检查执法包
    if project_agents.is_file():
        proj_text = read_text(project_agents)
        proj_block = section2_text(proj_text)
        if proj_block is None:
            warn("本项目 AGENTS.md 找不到 §2 章节，拒绝覆盖。请先人工修复。")
            return EXIT_STATE
        up_cols, up_labels = section2_signature(section2_text(up_text))
        proj_cols, proj_labels = section2_signature(proj_block)
        missing = [lab for lab in up_labels if lab not in proj_labels]
        if len(proj_cols) != len(up_cols) or missing:
            warn("§2 结构有变更，需要人工合并后才能继续（本次未写入任何文件）：")
            if len(proj_cols) != len(up_cols):
                warn("  - 列数：本项目 %d 列，上游 %d 列" % (len(proj_cols), len(up_cols)))
            for lab in missing:
                warn("  - 本项目缺少字段：%s" % lab)
            warn("  处理方式：在 AGENTS.md 的 §2 表格里补上以上字段并填值，再重跑本命令。")
            return EXIT_MERGE
        merged = compose_agents_md(up_text, proj_text)
    else:
        # 全新接入：§2 取值抹成占位符，禁止继承母版仓库自己的项目配置
        merged = section2_to_placeholder(up_text)

    local_ver = local_version(proj_root)
    up_ver = upstream_version(upstream)

    # 版本相同 + 没有旧结构残留 + 执法包不待更新 + .source 记录未失效，才是"无事可做"。
    legacy_pending = detect_legacy(proj_root)
    enforce_pending = False
    if not force and local_ver and local_ver == up_ver:
        # 版本没变不等于无事可做：上游模板可能演进了（托管落盘件自动更新）、
        # 或旧版部署的落盘件还在等一次性迁移、或 .source 死记录待修正。
        enforce_pending = enforcement_pending(proj_root, upstream, merged)
        if (
            not enforce_pending
            and not legacy_pending
            and source_record_current(proj_root, upstream)
        ):
            say("已是最新：本项目已是 v%s，无需变动。" % local_ver)
            return EXIT_OK
        if enforce_pending:
            say("版本相同，但执法包有待更新（上游模板演进或待迁移），继续对齐。")
    if legacy_pending:
        say("检测到旧结构残留，继续执行迁移：%s" % "、".join(legacy_pending))

    # 2) 旧结构迁移
    moved, leftover = migrate_legacy(proj_root, dry_run)

    # 3) 写盘
    try:
        changed = []
        if not project_agents.is_file() or read_text(project_agents) != merged:
            write_text_atomic(project_agents, merged, dry_run)
            changed.append(AGENTS_MD)

        for rel, src in collect_payload(upstream):
            dst = proj_root / rel
            if dst.is_file() and read_text(dst) == read_text(src):
                continue
            if not dry_run:
                dst.parent.mkdir(parents=True, exist_ok=True)
                write_text_atomic(dst, read_text(src))
            changed.append(rel.as_posix())

        agents_dir = proj_root / AGENTS_DIR
        # 模板从上游取（项目里不再留 project.example.py）
        example = upstream / AGENTS_DIR / PROJECT_EXAMPLE
        project_py = agents_dir / PROJECT_FILE
        source_file = agents_dir / SOURCE_FILE
        need_project_py = example.is_file() and not project_py.is_file()
        # .source 未记录当前上游（缺失 / 空文件 / 死路径 / 显式 --from 换过源）
        # 都以本次实际使用的上游为准写入/修正，防止下次裸 sync 静默回到旧上游
        need_source = not source_record_current(proj_root, upstream)
        # dry-run 也要计入预览（旧版漏报这两个文件，且汇报路径缺 .agents/ 前缀）
        if need_project_py:
            changed.append((Path(AGENTS_DIR) / PROJECT_FILE).as_posix())
        if need_source:
            changed.append((Path(AGENTS_DIR) / SOURCE_FILE).as_posix())
        if not dry_run and (need_project_py or need_source):
            agents_dir.mkdir(parents=True, exist_ok=True)
            if need_project_py:
                shutil.copyfile(str(example), str(project_py))
            if need_source:
                write_version(source_file, str(upstream))
        # VERSION 已随 collect_payload 的载荷循环写入，这里不再重复写

        # 执法包模板落盘（gate.yml 的分支名跟随 §2；归属由 tsc-managed 标记决定）
        deployed, enforced_updated, enforced_skipped = deploy_enforcement(
            proj_root, upstream, merged, dry_run
        )

    except PermissionError as exc:
        warn("写入失败（文件可能被占用）：%s" % exc)
        warn("请关闭占用该文件的应用后重试。")
        return EXIT_IO
    except OSError as exc:
        warn("写入失败：%s" % exc)
        return EXIT_IO

    # 4) 汇报
    say("上游来源：%s（v%s）" % (upstream, up_ver))
    say("目标项目：%s" % proj_root)
    say("版本变化：%s → %s" % (local_ver or "（未接入）", up_ver))
    if dry_run:
        say("模式：--dry-run，未写入任何文件")
    if changed:
        for name in changed:
            say("  %s %s" % ("将更新" if dry_run else "已更新", name))
    else:
        say("无文件需要变动。")

    if moved:
        say("旧结构%s .agents/：" % ("将迁移到" if dry_run else "已迁移到"))
        for src, dst in moved:
            say("  %s → %s" % (src.name, dst.relative_to(proj_root).as_posix()))
    for extra in leftover:
        say("旧位置已存在同名文件，未处理（请人工确认）：%s" % extra)

    if deployed:
        say("执法包新部署（%s）：" % ("将写入" if dry_run else "已写入"))
        for name in deployed:
            say("  %s" % name)
    if enforced_updated:
        say("执法包已随技能模板更新（%s）：" % ("将写入" if dry_run else "已写入"))
        for name in enforced_updated:
            say("  %s（带 tsc-managed 标记，视为技能托管）" % name)
    for name, why in enforced_skipped:
        say("执法包跳过 %s（%s；技能不覆盖项目接管的文件。如需对齐最新模板，"
            "请先自行备份再删掉该项目文件重跑 install）。" % (name, why))
    if deployed and not dry_run:
        say("还需人工做两件事：① 先 pip install pre-commit 与 "
            "npm i -D @commitlint/cli @commitlint/config-conventional，再执行 "
            "pre-commit install && pre-commit install --hook-type commit-msg"
            "（依赖没装好时钩子会拦死提交，不是自动跳过）；"
            "② 开分支保护（见技能目录 .agents/enforcement/README.md）。")

    if not (proj_root / AGENTS_DIR / PROJECT_FILE).is_file() and not dry_run:
        say("下一步：编辑 .agents/project.py，填入本项目自己的门禁命令。")

    # 瘦身提示：项目里若留着旧版复制进来的执行逻辑，只提示、不删除（契约 R-3.4）
    stale = detect_skill_only_leftovers(proj_root)
    if stale:
        say("")
        say("提示：以下文件是旧版复制进来的执行逻辑，现已统一由技能目录提供，")
        say("      留在项目里只是冗余（不影响功能）。确认后可自行删除：")
        for name in stale:
            say("  .agents/%s" % name)
        say("      删除属破坏性操作，脚本不会代劳——需要时请人工执行。")
    return EXIT_OK


# --------------------------------------------------------------------------- #
# 聚合门禁
# --------------------------------------------------------------------------- #
def load_project_config(proj_root):
    cfg_path = Path(proj_root) / AGENTS_DIR / PROJECT_FILE
    if not cfg_path.is_file():
        warn("找不到 %s，请先执行 install 或手工创建。" % cfg_path)
        return None
    namespace = {"__file__": str(cfg_path)}
    try:
        exec(compile(read_text(cfg_path), str(cfg_path), "exec"), namespace)
    except Exception as exc:  # noqa: BLE001 - 配置脚本语法错误必须显式暴露
        warn("%s 无法执行：%s" % (cfg_path, exc))
        return None
    return namespace


STEPS = [
    ("格式化 (Format)", "FMT_CHECK_CMD"),
    ("静态检查 (Lint)", "LINT_CMD"),
    ("测试 (Test)", "TEST_CMD"),
    ("构建 (Build)", "BUILD_CMD"),
]


def cmd_verify(proj_root):
    cfg = load_project_config(proj_root)
    if cfg is None:
        return EXIT_STATE

    ran = 0
    for label, key in STEPS:
        command = cfg.get(key)
        if command in (None, "", "skip"):
            say("skip: %s（未配置）" % label)
            continue
        say("$ %s" % command)
        completed = subprocess.run(command, shell=True, cwd=str(proj_root))
        code = completed.returncode
        if code < 0:
            # POSIX 下命令被信号杀死时 returncode 为负，负数退出码语义未定义
            warn("%s 被信号杀死（信号 %d），按 IO/执行错误处理。" % (label, -code))
            code = EXIT_IO
        ran += 1
        say("  退出码：%d" % code)
        if code != 0:
            warn("%s 未通过，停在此处。门禁结论：失败（退出码 %d）" % (label, code))
            return code
    if ran == 0:
        warn("四条门禁命令均未配置，本次没有真正执行任何检查——这个\"全绿\"是假绿。")
        warn("请编辑 .agents/project.py 填入真实命令（AGENTS.md §2 与之同步）。")
        say("门禁结论：无可执行项（假绿，退出码 0）")
        return EXIT_OK
    say("门禁结论：全绿（退出码 0）")
    return EXIT_OK


# --------------------------------------------------------------------------- #
# 配置一致性校验（AGENTS.md §2 与 project.py 必须同源）
# --------------------------------------------------------------------------- #
ROW_TO_KEY = {
    "格式化": "FMT_CHECK_CMD",
    "静态检查": "LINT_CMD",
    "测试": "TEST_CMD",
    "构建": "BUILD_CMD",
}


def normalize_value(value):
    if value is None:
        return "无"
    return str(value).strip().strip("`").strip()


def read_section2_values(proj_root):
    agents_md = Path(proj_root) / AGENTS_MD
    if not agents_md.is_file():
        return None
    block = section2_text(read_text(agents_md))
    if block is None:
        return None
    values = {}
    for line in block.split("\n"):
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 2:
            continue
        label = cells[0]
        for prefix, key in ROW_TO_KEY.items():
            if label.startswith(prefix) and key not in values:
                values[key] = cells[1]
    return values


def cmd_check_config(proj_root):
    cfg = load_project_config(proj_root)
    if cfg is None:
        return EXIT_STATE
    table = read_section2_values(proj_root)
    if table is None:
        warn("无法从 AGENTS.md 读出 §2 表格，检查中止。")
        return EXIT_STATE

    mismatch = []
    for key in ("FMT_CHECK_CMD", "LINT_CMD", "TEST_CMD", "BUILD_CMD"):
        if key not in cfg:
            say("%-14s project.py=（未定义该变量） §2=%s" % (key, table.get(key, "（§2 缺该行）")))
            mismatch.append(key)
            continue
        expected = normalize_value(cfg.get(key))
        actual = normalize_value(table.get(key, "（§2 缺该行）"))
        say("%-14s project.py=%-40s §2=%s" % (key, expected, actual))
        if expected != actual:
            mismatch.append(key)

    if mismatch:
        warn("不一致：%s" % "、".join(mismatch))
        warn("AGENTS.md §2 与 .agents/project.py 必须同源，请改成一致后重试。")
        return EXIT_MERGE
    say("一致：AGENTS.md §2 与 .agents/project.py 同源（退出码 0）")
    return EXIT_OK


# --------------------------------------------------------------------------- #
# 状态
# --------------------------------------------------------------------------- #
def cmd_status(proj_root, upstream):
    proj_root = Path(proj_root)
    say("项目根：%s" % proj_root)

    installed = (proj_root / AGENTS_DIR).is_dir() and (proj_root / AGENTS_MD).is_file()
    say("是否已接入：%s" % ("是" if installed else "否（先跑 install）"))

    say("当前版本：%s" % (local_version(proj_root) or "（无 .agents/VERSION）"))

    if upstream is not None:
        say("上游版本：%s（%s）" % (upstream_version(upstream) or "未知", upstream))
    else:
        say("上游版本：未指定（加 --from <路径> 可对比）")

    agents_md = proj_root / AGENTS_MD
    if agents_md.is_file():
        block = section2_text(read_text(agents_md))
        if block is None:
            say("§2 是否填好：找不到 §2 章节（AGENTS.md 不完整，先人工修复）")
        elif "[自动填充]" in block:
            say("§2 是否填好：否，仍有 [自动填充] 占位")
        else:
            say("§2 是否填好：是")

    project_py = proj_root / AGENTS_DIR / PROJECT_FILE
    say("门禁可跑：%s" % ("是" if project_py.is_file() else "否（缺 .agents/project.py）"))

    legacy = detect_legacy(proj_root)
    if legacy:
        say("检测到旧结构（跑 sync 会自动搬进 .agents/）：%s" % "、".join(legacy))

    stale = detect_skill_only_leftovers(proj_root)
    if stale:
        say("冗余执行逻辑（已由技能目录统一提供，项目里留着不影响功能）：%s" % "、".join(stale))
        say("  确认后可自行删除；删除属破坏性操作，脚本不会代劳。")
    return EXIT_OK


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def build_parser():
    parser = argparse.ArgumentParser(prog="tsc", description="契约分发与门禁")
    parser.add_argument(
        "command",
        choices=["status", "install", "sync", "verify", "check-config"],
        help="要执行的子命令",
    )
    parser.add_argument("--from", dest="source", default=None, help="上游来源（本地路径）")
    parser.add_argument("--dry-run", action="store_true", help="只报告，不写文件")
    parser.add_argument("--project", default=None, help="目标项目根（默认当前目录）")
    return parser


def main(argv=None):
    _init_stdout()
    args = build_parser().parse_args(argv)
    if args.project:
        proj_root = Path(normalize_path_arg(args.project)).expanduser().resolve()
    else:
        proj_root = Path.cwd()

    upstream = None
    if args.command in ("status", "install", "sync"):
        upstream = find_upstream(args.source, proj_root)
        missing = validate_upstream(upstream)
        if missing:
            warn("上游不完整，缺少：%s" % "、".join(missing))
            warn("上游路径：%s" % upstream)
            return EXIT_STATE

    if args.command == "status":
        return cmd_status(proj_root, upstream)
    if args.command == "verify":
        return cmd_verify(proj_root)
    if args.command == "check-config":
        return cmd_check_config(proj_root)

    if not proj_root.is_dir():
        warn("目标项目目录不存在：%s" % proj_root)
        return EXIT_STATE

    force = args.command == "install"
    return do_apply(proj_root, upstream, args.dry_run, force)


if __name__ == "__main__":
    sys.exit(main())
