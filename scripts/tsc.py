#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tsc —— 契约分发与门禁的唯一核心脚本（常驻插件 scripts/ 目录）。

用法（脚本留在插件目录，用 --project 指定目标项目）：
    python3 <插件根>/scripts/tsc.py status       --project <项目根>
    python3 <插件根>/scripts/tsc.py install     [--force] --project <项目根>
    python3 <插件根>/scripts/tsc.py sync         --project <项目根>
    python3 <插件根>/scripts/tsc.py update      [--timeout <秒>]
    python3 <插件根>/scripts/tsc.py verify      [--timeout <秒>] --project <项目根>
    python3 <插件根>/scripts/tsc.py check-config --project <项目根>
    python3 <插件根>/scripts/tsc.py doctor      [--json] --project <项目根>
    python3 <插件根>/scripts/tsc.py rollback     --project <项目根>

    `--project` 省略时取当前工作目录，因此"cd 到项目里再跑"也成立。

命令边界（两类升级严格分开，不要混为一谈）：
    update   只更新 TSC 技能/插件本体（git pull；非 git 安装副本走宿主更新机制）
    sync     只更新当前项目契约（来源恒为"当前已安装的本体"，绝不读项目 .source）
    install  首次接入；目标项目已有外部 AGENTS.md 时必须 --force 显式接管
    doctor   只读诊断，给出 ready / not-ready 结论
    rollback 恢复上一次 install/sync 写盘之前的项目契约状态

通用参数：
    --source <路径>  显式上游（本地插件/技能目录），默认=本脚本所在插件根
    --from <路径>    同 --source（旧名兼容）
    --project <路径> 目标项目根（默认当前目录）
    --dry-run        只报告将发生的变化，不写任何文件
    --force          install 时确认接管外部 AGENTS.md
    --timeout <秒>   verify 每条门禁命令 / update 网络操作的超时（默认 600）
    --json           status / doctor 输出 JSON
    --version        打印本体版本

退出码：
    0    成功 / 已是最新
    1    需要人工处理（§2 结构变更、外部 AGENTS.md 未接管、§2 与 project.py 不一致）
    2    IO / 编码 / 权限错误
    3    状态非法（缺 §2、缺 VERSION、上游无效、门禁全未配置、无可回滚记录、本体不可 git 更新）
    124  门禁命令超时被终止

设计约束：
    - 零第三方依赖，仅用标准库。
    - 所有文本读写强制 UTF-8 与 LF，避免 Windows 默认 CRLF 破坏行数门禁口径。
    - 上游来源只接受本地路径（已安装的本体本身就是上游）；不联网（update 除外）。
    - 绝不自动删除文件；旧结构只做"移动 + 提示"（rollback 删除的仅限上次 apply 新建的文件）。
    - 执法包（enforcement）默认随 install 落盘；带 tsc-managed 标记的才托管更新。
    - Node/JS 项目才部署 commitlint；纯 Python 项目绝不引入 npm 依赖。
"""

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

EXIT_OK = 0
EXIT_MERGE = 1
EXIT_IO = 2
EXIT_STATE = 3
EXIT_TIMEOUT = 124

AGENTS_MD = "AGENTS.md"
AGENTS_DIR = ".agents"
VERSION_FILE = "VERSION"
SOURCE_FILE = ".source"
PROJECT_FILE = "project.py"
SECTION2_HEADING = "## 2."

# 插件/技能布局：本脚本在 <插件根>/scripts/ 下，上游根即其上一级。
SCRIPT_SUBDIR = "scripts"
TEMPLATE_AGENTS = "templates/AGENTS.md"
TEMPLATE_PROJECT_EXAMPLE = "templates/project.example.py"
ENFORCE_SUBDIR = "templates/enforcement"

# 执法包模板 → 落地位置。commitlint 仅 Node/JS 项目部署（见 NODE_ONLY_ENFORCE）。
ENFORCE_DEPLOY = {
    ENFORCE_SUBDIR + "/gate.yml": ".github/workflows/gate.yml",
    ENFORCE_SUBDIR + "/.pre-commit-config.yaml": ".pre-commit-config.yaml",
    ENFORCE_SUBDIR + "/commitlint.config.js": "commitlint.config.js",
    SCRIPT_SUBDIR + "/structure_guard.py": ".agents/structure_guard.py",
    SCRIPT_SUBDIR + "/bracket_lint.py": ".agents/bracket_lint.py",
}
# 只属于 Node/JS 项目的执法件：非 Node 项目一律不部署。
NODE_ONLY_ENFORCE = {ENFORCE_SUBDIR + "/commitlint.config.js"}
NODE_MANIFEST = "package.json"

# 执法包归属标记：带此标记 = 技能托管，可随上游模板更新；删掉标记再改 = 项目接管，永不覆盖。
MANAGED_MARKER = "tsc-managed"
# AGENTS.md 所有权标记：带此标记 = TSC 托管契约，允许按 TSC 规则更新托管内容。
CONTRACT_MARKER = "tsc-managed-contract"
CONTRACT_MARKER_VERSION = "v4"
CONTRACT_MARKER_LINE = "<!-- %s:%s -->" % (CONTRACT_MARKER, CONTRACT_MARKER_VERSION)

# 行首注释符：标记必须紧跟其后才算"声明"；正文里提及标记字符串不作数。
COMMENT_PREFIXES = ("<!--", "//", "#")


def is_marker_line(line, marker):
    """该行是否"整行声明"了归属标记。

    只有注释符打头、且注释正文以 marker 开头的行才算声明，例如
    `<!-- tsc-managed-contract:v4 -->`、`# tsc-managed —— ...`、`// tsc-managed —— ...`。
    说明文字（如"本文件带 tsc-managed 标记"）、被反引号/引号包起来的示例都不算——
    否则"提及"会被误判成"声明"，进而覆盖本不该接管的文件。
    """
    text = line.strip()
    for prefix in COMMENT_PREFIXES:
        if text.startswith(prefix):
            return text[len(prefix):].lstrip().startswith(marker)
    return False


def has_marker(content, marker):
    """内容中是否存在整行标记声明（任一行命中即可）。"""
    return any(is_marker_line(line, marker) for line in content.splitlines())


# .pre-commit-config.yaml 里的 Node 专属区块：非 Node 项目部署时整段剔除。
NODE_REGION_BEGIN = "# tsc:begin:node-only"
NODE_REGION_END = "# tsc:end:node-only"

DEFAULT_TIMEOUT_S = 600

# 门禁超时可在项目 project.py 里按步覆盖：GATE_TIMEOUTS = {"TEST_CMD": 300}
GATE_TIMEOUTS_KEY = "GATE_TIMEOUTS"

PLACEHOLDER = "[自动填充]"

SKILL_ONLY_LEFTOVERS = [
    # 旧版本曾复制进项目的执行逻辑；现已统一由插件目录提供，只提示、不删除。
    "tsc.py",
    "AUDIT-SPEC.md",
    "BOOTSTRAP.md",
    "verify.ps1",
    "verify.sh",
    "install_hook.py",
    "test",
    "project.example.py",
    "enforcement",
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
    """先写临时文件再替换，避免留下半成品；替换失败时清理临时文件并原样抛错。"""
    if dry_run:
        return
    path = Path(path)
    tmp = path.with_name(path.name + ".tsc-tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass  # 清理失败不得掩盖原始错误——原始异常在下方原样抛出
        raise


# --------------------------------------------------------------------------- #
# §2 项目区：锚点切分与结构校验
# --------------------------------------------------------------------------- #
def split_table_row(line):
    r"""按未转义的 | 切分一行 Markdown 表格；\| 视作字面竖线（原样保留，不在此处还原）。

    命令里真实的管道（如 `pytest -q | tee t.log`）在 §2 中应写作 `\|`；
    Windows 路径里的孤立反斜杠不受影响。
    """
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    cells, cur, esc = [], [], False
    for ch in text:
        if esc:
            cur.append(ch)
            esc = False
        elif ch == "\\":
            cur.append(ch)
            esc = True
        elif ch == "|":
            cells.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    cells.append("".join(cur).strip())
    return cells


def unescape_cell(text):
    r"""把表格 cell 里的 \| 还原为字面 |（供与 project.py 的真实命令比较）。"""
    return text.replace("\\|", "|")


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
        cells = split_table_row(stripped)
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
# 上游定位：显式 --source > 当前已安装本体（本脚本所在插件根）。
# 项目的 .agents/.source 只是 provenance（来源记录），**绝不参与上游解析**——
# 否则旧安装源会压过当前 Skill，"更新后裸 sync"仍同步旧版本（v3.x P1-01）。
# --------------------------------------------------------------------------- #
def script_dir():
    return Path(__file__).resolve().parent


def upstream_root():
    """当前已安装本体的根目录：scripts/tsc.py 的上一级。"""
    return script_dir().parent


def normalize_path_arg(value):
    """兼容 Git Bash / MSYS 风格的 /c/Users/... 路径。

    Windows 上从 Git Bash 传 --project /c/foo 会被 Python 解析成 C:\\c\\foo，
    这里统一还原成 C:/foo，避免"路径看着对、实际找不到"的假故障。
    """
    text = str(value)
    if (
        os.name == "nt"
        and len(text) >= 3
        and text[0] == "/"
        and text[1].isalpha()
        and text[2] == "/"
    ):
        return text[1].upper() + ":" + text[2:]
    return text


def find_upstream(explicit):
    if explicit:
        return Path(normalize_path_arg(explicit)).expanduser().resolve()
    return upstream_root()


def validate_upstream(root):
    return [
        name
        for name in (VERSION_FILE, TEMPLATE_AGENTS, TEMPLATE_PROJECT_EXAMPLE)
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
# .source：结构化 provenance（来源记录），供 status / doctor 展示。
# 旧版是纯路径文本，读取时兼容；写入一律 JSON。**不参与上游解析。**
# --------------------------------------------------------------------------- #
def _source_record_payload(upstream, up_ver):
    return {
        "source": str(upstream),
        "version": up_ver,
        "installed_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    }


def write_source_record(proj_root, upstream, up_ver, dry_run=False):
    write_text_atomic(
        Path(proj_root) / AGENTS_DIR / SOURCE_FILE,
        json.dumps(_source_record_payload(upstream, up_ver), ensure_ascii=False, indent=2) + "\n",
        dry_run,
    )


def read_source_record(proj_root):
    """读取 provenance。返回 dict（至少含 source）；缺失/损坏返回 None。"""
    path = Path(proj_root) / AGENTS_DIR / SOURCE_FILE
    if not path.is_file():
        return None
    raw = read_text(path).strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("source"):
            return data
    except ValueError:
        pass
    return {"source": raw, "legacy": True}  # 旧版纯路径文本


def source_record_current(proj_root, upstream, up_ver):
    """provenance 是否已记录当前上游与版本（仅用于漂移检测，不用于选源）。"""
    record = read_source_record(proj_root)
    if record is None or record.get("legacy"):
        return False
    return (
        record.get("source") == str(upstream)
        and record.get("version") == up_ver
    )


# --------------------------------------------------------------------------- #
# AGENTS.md 所有权：marker 决定一切，绝不凭"§2 长得像"认定所有权
# --------------------------------------------------------------------------- #
def contract_ownership(proj_root):
    """判定项目 AGENTS.md 的所有权。

    返回：
        none        没有 AGENTS.md（全新接入）
        managed     带"整行" tsc-managed-contract 标记（TSC 托管；正文里提及该字符串不算）
        legacy      无标记，但 .agents/VERSION 是 TSC 部署的版本文件
                    （旧版安装的项目；只允许一次性升级：重建时补上标记）
        foreign     外部项目自己的 AGENTS.md（无标记、无 TSC 部署证据）——默认只读，不接管
    """
    agents_md = Path(proj_root) / AGENTS_MD
    if not agents_md.is_file():
        return "none"
    if has_marker(read_text(agents_md), CONTRACT_MARKER):
        return "managed"
    if (Path(proj_root) / AGENTS_DIR / VERSION_FILE).is_file():
        return "legacy"
    return "foreign"


OWNERSHIP_LABEL = {
    "none": "未接入",
    "managed": "TSC 托管（%s）" % CONTRACT_MARKER_LINE,
    "legacy": "旧版 TSC 部署（缺所有权标记，首次 sync 会补上）",
    "foreign": "外部 AGENTS.md（非 TSC 托管，默认只读）",
}


# --------------------------------------------------------------------------- #
# Node/JS 探测：只有 Node 项目才引入 commitlint 等 npm 依赖
# --------------------------------------------------------------------------- #
def is_node_project(proj_root):
    return (Path(proj_root) / NODE_MANIFEST).is_file()


def strip_node_regions(text):
    """剔除 # tsc:begin:node-only ... # tsc:end:node-only 之间的区块（含标记行）。"""
    out, depth = [], 0
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped == NODE_REGION_BEGIN:
            depth += 1
            continue
        if stripped == NODE_REGION_END:
            depth = max(0, depth - 1)
            continue
        if depth == 0:
            out.append(line)
    return "\n".join(out)


def enforce_template_content(rel_src, proj_root, upstream, merged_agents_text):
    """算出某执法模板落在该项目里的最终内容；模板不存在返回 None。"""
    src = Path(upstream) / rel_src
    if not src.is_file():
        return None
    content = read_text(src)
    main_branch = section2_value(section2_text(merged_agents_text), "主干分支")
    if rel_src.endswith("gate.yml"):
        if main_branch and (
            PLACEHOLDER in main_branch or main_branch.strip() in ("无", "—", "")
        ):
            main_branch = None  # §2 占位或未填（如非 git 项目）→ 保持模板默认 [main]
        if main_branch:
            content = content.replace("branches: [main]", "branches: [%s]" % main_branch)
    if not is_node_project(proj_root):
        # 非 Node 项目：剔除 Node 专属区块（commitlint 整文件已在部署清单里排除）
        content = strip_node_regions(content)
    return content


# --------------------------------------------------------------------------- #
# 旧结构迁移（只移动，不删除）
# --------------------------------------------------------------------------- #
# 旧版契约把 AUDIT-SPEC.md / BOOTSTRAP.md / enforcement/ / test/ 散在项目根目录。
# 其中 enforcement / test 是通用名，项目自己的同名目录绝不能误搬：
#   1) 项目根必须先有 AGENTS.md（确曾部署过契约）才谈得上"旧结构"；
#   2) 通用名目录必须带 ≥2 个契约内容签名才认——单个同名文件不足以认定。
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
        hits = sum(1 for s in signatures if (subdir / s).exists())
        if subdir.is_dir() and hits >= 2:
            found.append(name)
    return found


def detect_skill_only_leftovers(proj_root):
    """项目 .agents/ 里残留的执行逻辑（现由插件目录统一提供）。只用于提示，不删除。

    扫描目标本身就是上游/插件目录时返回空——那里的逻辑是正本，不是冗余。
    """
    proj_root = Path(proj_root)
    try:
        if proj_root.resolve() == upstream_root().resolve():
            return []
    except OSError:
        pass
    agents_dir = proj_root / AGENTS_DIR
    return [n for n in SKILL_ONLY_LEFTOVERS if (agents_dir / n).exists()]


def migrate_legacy(proj_root, dry_run):
    """把根目录的旧布局搬进 .agents/。返回 (已移动, 建议人工处理)。

    搬移中途失败时，先逆序搬回已完成的部分再抛错——调用方据此保证整体原状。
    """
    proj_root = Path(proj_root)
    agents_dir = proj_root / AGENTS_DIR
    moved, leftover = [], []
    for name in detect_legacy(proj_root):
        src = proj_root / name
        dst = agents_dir / name
        if dst.exists():
            leftover.append(src)
            continue
        if not dry_run:
            agents_dir.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(str(src), str(dst))
            except OSError:
                for s, d in reversed(moved):
                    try:
                        shutil.move(str(d), str(s))
                    except OSError:
                        pass  # 回滚自身的失败不得掩盖原始错误，原始异常原样抛出
                raise
        moved.append((src, dst))
    return moved, leftover


# --------------------------------------------------------------------------- #
# 同步主流程
# --------------------------------------------------------------------------- #
def collect_payload(upstream):
    """需要分发到项目的文件：键为相对项目根的路径，值为上游源文件。

    只分发"必须躺在项目里"的东西：版本号一个。执行逻辑（tsc.py / AUDIT-SPEC /
    BOOTSTRAP / verify.* / test / 执法包模板原件）一律留在插件目录，不往项目里复制。
    注意：**不包含 AGENTS.md**——它需要与项目现有 §2 合成后单独写。
    """
    return [(Path(AGENTS_DIR) / VERSION_FILE, upstream / VERSION_FILE)]


def section2_to_placeholder(text):
    """把 §2 表格的「命令 / 取值」列整体替换为占位符（结构与验证条件列保持原样）。

    用于全新 install：目标项目还没探测过环境，绝不能继承母版仓库自己的取值。
    """
    span = section2_span(text)
    if span is None:
        return text
    lines = text.split("\n")
    start, end = span
    out = []
    header_seen = False
    for i, line in enumerate(lines):
        if start <= i < end:
            stripped = line.strip()
            if stripped.startswith("|"):
                cells = split_table_row(stripped)
                if cells and set("".join(cells)) <= set("-: "):
                    out.append(line)  # 表头分隔行
                    continue
                if not header_seen:
                    header_seen = True  # 表头行（不假设首列标签字面）
                    out.append(line)
                    continue
                if len(cells) >= 2:
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
        cells = split_table_row(stripped)
        if len(cells) < 2 or set("".join(cells)) <= set("-: "):
            continue
        if cells[0].startswith(row_prefix):
            return cells[1]
    return None


def _enforce_actions(proj_root, upstream, merged_agents_text):
    """算出执法包落盘动作，不写任何文件（判定单源，供部署与早退检查共用）。

    归属规则（MANAGED_MARKER = "tsc-managed"，须为整行注释声明，正文提及不算）：
    - 项目文件带标记 → 技能托管：以上游模板为准，内容不同就更新；
    - 不带标记但正文与模板一致（忽略标记行与 gate.yml 分支名）→ 旧版部署
      的文件，一次性升级为带标记的托管版；
    - 不带标记且正文不同 → 项目已接管，永不覆盖，只提示。
    - commitlint.config.js 只在 Node/JS 项目部署；.pre-commit-config.yaml 的
      Node 专属区块在非 Node 项目中剔除（Python-only 项目绝不引入 npm 依赖）。
    返回 (新部署, 已更新, 跳过)。
    """
    proj_root = Path(proj_root)
    try:
        if proj_root.resolve() == Path(upstream).resolve():
            # 母版/插件目录自举：模板原件已在 templates/，不往自己根目录铺生效件
            return [], [], []
    except OSError:
        pass
    node = is_node_project(proj_root)
    deploy, update, skip = [], [], []

    def normalize(text):
        # 去掉归属标记行，行尾统一，用于"正文是否一致"的比较
        lines = [ln for ln in text.splitlines() if not is_marker_line(ln, MANAGED_MARKER)]
        return "\n".join(lines).rstrip("\n")

    def debranch(text):
        # 把技能自动部署的分支名归一回模板默认值，供比较用；
        # 用户手改的其他分支名不会被归一，仍判为"内容不同"。
        main_branch = section2_value(section2_text(merged_agents_text), "主干分支")
        if main_branch and PLACEHOLDER not in main_branch:
            return text.replace("branches: [%s]" % main_branch, "branches: [main]")
        return text

    for rel_src, rel_dst in ENFORCE_DEPLOY.items():
        if rel_src in NODE_ONLY_ENFORCE and not node:
            continue  # Python-only 项目不部署 commitlint
        content = enforce_template_content(rel_src, proj_root, upstream, merged_agents_text)
        if content is None:
            continue
        template = read_text(Path(upstream) / rel_src)
        dst = proj_root / rel_dst

        if not dst.is_file():
            deploy.append((rel_dst, content))
            continue

        existing = read_text(dst)
        if has_marker(existing, MANAGED_MARKER):
            # 技能托管：上游模板说了算
            if existing != content:
                update.append((rel_dst, content))
            continue

        # 旧版部署的一次性迁移：正文一致（忽略标记行/分支名/Node 区块差异）→ 升级为托管版
        if normalize(debranch(existing)) == normalize(strip_node_regions(template)):
            update.append((rel_dst, content))
            continue

        skip.append((rel_dst, "内容已被项目改过"))

    return deploy, update, skip


def deploy_enforcement(proj_root, upstream, merged_agents_text, dry_run, journal=None):
    """把执法包模板落到生效位置（gate.yml 的主干分支名跟随 §2）。

    dry_run 只报告不写盘。journal 传入列表时，每个已写文件以
    (路径, 原内容或 None=新文件) 记入，供调用方失败回滚。返回 (新部署, 已更新, 跳过) 三个名字列表。
    """
    deploy, update, skip = _enforce_actions(proj_root, upstream, merged_agents_text)
    if not dry_run:
        for rel_dst, content in deploy + update:
            dst = Path(proj_root) / rel_dst
            original = read_text(dst) if dst.is_file() else None
            dst.parent.mkdir(parents=True, exist_ok=True)
            write_text_atomic(dst, content)
            if journal is not None:
                journal.append((dst, original))
    return (
        [name for name, _ in deploy],
        [name for name, _ in update],
        skip,
    )


BACKUP_DIRNAME = ".tsc-backup"


def persist_backup(proj_root, journal, contract_ver):
    """apply 全部成功后，把本次改动前的原状写成可回滚清单（单级：只留上一次）。"""
    backup_dir = Path(proj_root) / AGENTS_DIR / BACKUP_DIRNAME
    records = []
    for dst, original in journal:
        try:
            rel = Path(dst).resolve().relative_to(Path(proj_root).resolve()).as_posix()
        except ValueError:
            continue  # 项目根之外的路径不进清单
        records.append(
            {
                "path": rel,
                "action": "modify" if original is not None else "create",
                "content": original,
            }
        )
    if not records:
        return
    manifest = {
        "contract_version": contract_ver,
        "backed_up_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "files": records,
    }
    backup_dir.mkdir(parents=True, exist_ok=True)
    write_text_atomic(
        backup_dir / "manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    )


def do_apply(proj_root, upstream, dry_run, force):
    """install / sync 共用的落地逻辑。返回退出码。

    所有权规则（绝不凭 §2 形状认定所有权）：
    - 无 AGENTS.md          → 全新接入；
    - 带 contract marker    → 托管，按 TSC 规则更新托管内容；
    - 旧版部署（无 marker 但有 .agents/VERSION）→ 一次性升级，重建时补 marker；
    - 外部 AGENTS.md        → 拒绝写入；仅 install --force（显式接管）例外。
    """
    proj_root = Path(proj_root)
    project_agents = proj_root / AGENTS_MD

    up_text = read_text(upstream / TEMPLATE_AGENTS)
    if section2_span(up_text) is None:
        warn("上游模板 %s 找不到 §2 章节，拒绝继续（防止整文件覆盖）。" % TEMPLATE_AGENTS)
        return EXIT_STATE

    ownership = contract_ownership(proj_root)

    # 1) 先合并出目标 AGENTS.md：同版本的早退判定也要用它检查执法包
    if project_agents.is_file():
        proj_text = read_text(project_agents)
        proj_block = section2_text(proj_text)
        if proj_block is None:
            warn("本项目 AGENTS.md 找不到 §2 章节，拒绝覆盖。请先人工修复。")
            return EXIT_STATE
        if ownership == "foreign" and not force:
            warn("本项目 AGENTS.md 不是 TSC 托管契约（缺少 %s 标记），sync/install 默认不接管。" % CONTRACT_MARKER)
            warn("冲突摘要：")
            warn("  - 所有权：%s" % OWNERSHIP_LABEL["foreign"])
            _warn_foreign_summary(up_text, proj_text)
            warn("  处理方式：确认要把本项目纳入 TSC 托管后，执行 install --force 显式接管（保留本项目 §2 取值）。")
            return EXIT_MERGE
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
        if ownership == "foreign":
            warn("已按 --force 显式接管：AGENTS.md 将以 TSC 母版重建（仅保留本项目 §2 取值），并补上所有权标记。")
    else:
        # 全新接入：§2 取值抹成占位符，禁止继承母版仓库自己的项目配置
        merged = section2_to_placeholder(up_text)

    local_ver = local_version(proj_root)
    up_ver = upstream_version(upstream)
    legacy_pending = detect_legacy(proj_root)

    # 预计算将发生的写入（不落盘）。同步判据 = 逐项内容漂移，版本号只是展示信息：
    # 上游改了内容但忘 bump 版本，sync 照样把差异写下去。
    drift = []
    if not project_agents.is_file() or read_text(project_agents) != merged:
        drift.append(AGENTS_MD)
    for rel, src in collect_payload(upstream):
        dst = proj_root / rel
        if not dst.is_file() or read_text(dst) != read_text(src):
            drift.append(rel.as_posix())
    example = upstream / TEMPLATE_PROJECT_EXAMPLE
    if example.is_file() and not (proj_root / AGENTS_DIR / PROJECT_FILE).is_file():
        drift.append((Path(AGENTS_DIR) / PROJECT_FILE).as_posix())
    if not source_record_current(proj_root, upstream, up_ver):
        drift.append((Path(AGENTS_DIR) / SOURCE_FILE).as_posix())
    deploy, update, enforce_skipped = _enforce_actions(proj_root, upstream, merged)
    drift.extend(deploy)
    drift.extend(update)
    drift.extend(legacy_pending)

    if not force and not drift:
        say("已是最新：上游 v%s，逐项内容比对无漂移，无需变动。" % up_ver)
        for name, why in enforce_skipped:
            say("执法包跳过 %s（%s；项目已接管，技能不覆盖）。" % (name, why))
        return EXIT_OK
    if legacy_pending:
        say("检测到旧结构残留，继续执行迁移：%s" % "、".join(legacy_pending))

    # 2) 写盘（带内存日志：任一步失败，已写入的部分整体回滚为操作前原状）
    journal = []  # (路径, 原内容；None 表示本操作新建的文件)

    def journal_write(dst, text, journal=journal, dry_run=dry_run):
        dst = Path(dst)
        original = read_text(dst) if dst.is_file() else None
        write_text_atomic(dst, text, dry_run)
        if not dry_run:
            journal.append((dst, original))

    def rollback_journal(journal=journal):
        # 尽力恢复；单文件恢复失败只如实列出，不掩盖原始错误
        problems = []
        for dst, original in reversed(journal):
            try:
                if original is None:
                    dst.unlink()
                else:
                    write_text_atomic(dst, original)
            except OSError as exc:
                problems.append("%s（%s）" % (dst, exc))
        return problems

    try:
        changed = []
        if not project_agents.is_file() or read_text(project_agents) != merged:
            journal_write(project_agents, merged)
            changed.append(AGENTS_MD)

        for rel, src in collect_payload(upstream):
            dst = proj_root / rel
            if dst.is_file() and read_text(dst) == read_text(src):
                continue
            if not dry_run:
                dst.parent.mkdir(parents=True, exist_ok=True)
                journal_write(dst, read_text(src))
            changed.append(rel.as_posix())

        agents_dir = proj_root / AGENTS_DIR
        # 模板从上游取（项目里不再留 project.example.py）
        project_py = agents_dir / PROJECT_FILE
        need_project_py = example.is_file() and not project_py.is_file()
        # provenance 未记录当前上游/版本时重写（缺失 / 旧格式 / 换过显式 --source）
        need_source = not source_record_current(proj_root, upstream, up_ver)
        if need_project_py:
            changed.append((Path(AGENTS_DIR) / PROJECT_FILE).as_posix())
        if need_source:
            changed.append((Path(AGENTS_DIR) / SOURCE_FILE).as_posix())
        if not dry_run and (need_project_py or need_source):
            agents_dir.mkdir(parents=True, exist_ok=True)
            if need_project_py:
                original = read_text(project_py) if project_py.is_file() else None
                shutil.copyfile(str(example), str(project_py))
                journal.append((project_py, original))
            if need_source:
                journal_write(
                    agents_dir / SOURCE_FILE,
                    json.dumps(_source_record_payload(upstream, up_ver), ensure_ascii=False, indent=2) + "\n",
                )

        # 执法包模板落盘（gate.yml 的分支名跟随 §2；归属由 tsc-managed 标记决定）
        deployed, enforced_updated, enforced_skipped = deploy_enforcement(
            proj_root, upstream, merged, dry_run, journal=journal
        )

    except PermissionError as exc:
        problems = rollback_journal()
        warn("写入失败（文件可能被占用），已回滚本次全部改动：%s" % exc)
        for p in problems:
            warn("  回滚未彻底，请人工检查：%s" % p)
        warn("请关闭占用该文件的应用后重试。")
        return EXIT_IO
    except OSError as exc:
        problems = rollback_journal()
        warn("写入失败，已回滚本次全部改动：%s" % exc)
        for p in problems:
            warn("  回滚未彻底，请人工检查：%s" % p)
        return EXIT_IO

    if not dry_run:
        persist_backup(proj_root, journal, up_ver)

    # 3) 旧结构迁移（放在所有写盘成功之后：失败也只是"目标未完成"，不会先搬走旧目录）
    try:
        moved, leftover = migrate_legacy(proj_root, dry_run)
    except OSError as exc:
        problems = rollback_journal()
        warn("旧结构迁移失败，已回滚本次全部写入：%s" % exc)
        for p in problems:
            warn("  回滚未彻底，请人工检查：%s" % p)
        return EXIT_IO

    # 4) 汇报
    say("上游来源：%s（v%s）" % (upstream, up_ver))
    say("目标项目：%s" % proj_root)
    say("版本变化：%s → %s" % (local_ver or "（未接入）", up_ver))
    say("所有权：%s" % OWNERSHIP_LABEL[ownership])
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

    if not dry_run:
        if is_node_project(proj_root):
            say("Node 项目：commitlint 已随执法包部署。启用本地钩子前先装依赖：")
            say("  npm i -D @commitlint/cli @commitlint/config-conventional")
        else:
            say("未检测到 package.json：按非 Node 项目处理，不部署 commitlint、不引入任何 npm 依赖。")
        say("本地钩子激活（可选，不想被拦就别执行）：pip install pre-commit && "
            "pre-commit install && pre-commit install --hook-type commit-msg")
        say("密钥扫描 / commitlint 的全量兜底在 CI（.github/workflows/gate.yml），无需本地依赖。")

    if not (proj_root / AGENTS_DIR / PROJECT_FILE).is_file() and not dry_run:
        say("下一步：编辑 .agents/project.py，填入本项目自己的门禁命令。")

    # 瘦身提示：项目里若留着旧版复制进来的执行逻辑，只提示、不删除（契约 R-3.4）
    stale = detect_skill_only_leftovers(proj_root)
    if stale:
        say("")
        say("提示：以下文件是旧版复制进来的执行逻辑，现已统一由插件目录提供，")
        say("      留在项目里只是冗余（不影响功能）。确认后可自行删除：")
        for name in stale:
            say("  .agents/%s" % name)
        say("      删除属破坏性操作，脚本不会代劳——需要时请人工执行。")
    return EXIT_OK


def _warn_foreign_summary(up_text, proj_text):
    """外部 AGENTS.md 冲突摘要：不动文件，只让用户看清接管会发生什么。"""
    up_cols, up_labels = section2_signature(section2_text(up_text))
    proj_block = section2_text(proj_text)
    proj_cols, proj_labels = section2_signature(proj_block) if proj_block else ([], [])
    warn("  - 接管后：正文以 TSC 母版重建，并写入 %s" % CONTRACT_MARKER_LINE)
    if proj_labels:
        only_project = [lab for lab in proj_labels if lab not in up_labels]
        if only_project:
            warn("  - 本项目 §2 有上游没有的字段：%s（接管前需先对齐 §2 结构）" % "、".join(only_project))
        else:
            warn("  - 本项目 §2 取值将原样保留")


# --------------------------------------------------------------------------- #
# 聚合门禁（每条命令都有超时；超时杀整个进程组，绝不无限等待）
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


def _popen_kwargs():
    """让子进程独成进程组，超时时能整组击杀（shell 的孙进程也不例外）。"""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _kill_process_group(proc):
    """终止整棵进程树（含 shell 的孙进程）。

    只杀 shell 本身不够：孙进程会继续持有调用方的 stdout/stderr 管道，
    让上层 capture_output 一直阻塞到孙进程自然退出（本机实测 60s+）。
    """
    if os.name == "nt":
        # taskkill /T 按父子关系杀整棵树；不可用时再退回单进程终止。
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            pass  # taskkill 缺失/超时——下面的单进程终止仍会执行，超时结论不受影响
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass  # 进程已自行退出或无权终止——不得掩盖超时结论
    if proc.poll() is None:
        try:
            proc.kill()
        except OSError:
            pass  # 刚被 taskkill 带走——同样不得掩盖超时结论


def _reap_bounded(proc, grace_s):
    """有界收割已终止的进程，返回是否已收到退出。

    不能用第二次 communicate()：CPython 在 _communication_started 已置位时会
    忽略传入的 timeout，本意"最多等 grace_s"会变成"一直等"。
    """
    endtime = time.monotonic() + grace_s
    while True:
        remaining = endtime - time.monotonic()
        if remaining <= 0:
            return False
        try:
            proc.wait(timeout=min(0.5, remaining))
            return True
        except subprocess.TimeoutExpired:
            continue


def run_gate_command(command, cwd, timeout_s):
    """带超时地执行一条门禁命令。返回 (退出码, 是否超时)。"""
    proc = subprocess.Popen(
        command, shell=True, cwd=str(cwd), **_popen_kwargs()
    )
    try:
        proc.communicate(timeout=max(1, int(timeout_s)))
        return proc.returncode, False
    except subprocess.TimeoutExpired:
        _kill_process_group(proc)
        _reap_bounded(proc, 10)
        return EXIT_TIMEOUT, True


def cmd_verify(proj_root, timeout_override=None):
    cfg = load_project_config(proj_root)
    if cfg is None:
        return EXIT_STATE

    per_step = cfg.get(GATE_TIMEOUTS_KEY) or {}
    ran = 0
    for label, key in STEPS:
        command = cfg.get(key)
        if command in (None, "", "skip"):
            say("skip: %s（未配置）" % label)
            continue
        timeout_s = timeout_override or per_step.get(key) or DEFAULT_TIMEOUT_S
        say("$ %s（超时 %ss）" % (command, timeout_s))
        code, timed_out = run_gate_command(command, proj_root, timeout_s)
        if timed_out:
            warn("%s 超过 %ss 未结束：已终止整个进程组，绝不无限等待。" % (label, timeout_s))
            warn("门禁结论：超时（退出码 %d）。如该命令确实需要更久，用 --timeout 或 "
                 "project.py 的 %s[\"%s\"] 放宽。" % (EXIT_TIMEOUT, GATE_TIMEOUTS_KEY, key))
            return EXIT_TIMEOUT
        if code is not None and code < 0:
            # POSIX 下命令被信号杀死时 returncode 为负，负数退出码语义未定义
            warn("%s 被信号杀死（信号 %d），按 IO/执行错误处理。" % (label, -code))
            code = EXIT_IO
        ran += 1
        say("  退出码：%s" % code)
        if code != 0:
            warn("%s 未通过，停在此处。门禁结论：失败（退出码 %s）" % (label, code))
            return code
    if ran == 0:
        warn("四条门禁命令均未配置，本次没有真正执行任何检查——这个\"全绿\"是假绿，未配置不是通过。")
        warn("请编辑 .agents/project.py 填入真实命令（AGENTS.md §2 与之同步）。")
        warn("门禁结论：未配置（退出码 %d）" % EXIT_STATE)
        return EXIT_STATE
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
        cells = split_table_row(stripped)
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
        actual = normalize_value(unescape_cell(table.get(key, "（§2 缺该行）")))
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
# update：只更新技能/插件本体（与项目 sync 严格分开）
# --------------------------------------------------------------------------- #
def cmd_update(timeout_s):
    root = upstream_root()
    old_ver = upstream_version(root) or "未知"
    if not (root / ".git").exists():
        warn("当前安装副本不含 .git（通常由宿主插件市场或压缩包安装，本脚本无从拉取）。")
        warn("本体更新请走宿主机制：ZCode → 设置 → 插件管理 → tsc → 更新；")
        warn("或用 git clone / 市场重装修复后重试。项目契约不受影响，仍可 sync/verify。")
        return EXIT_STATE
    say("本体目录：%s（当前 v%s）" % (root, old_ver))
    say("$ git -C %s pull --ff-only（超时 %ss）" % (root, timeout_s))
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "pull", "--ff-only"],
            capture_output=True, timeout=max(1, int(timeout_s)),
        )
    except subprocess.TimeoutExpired:
        warn("git pull 超过 %ss 未结束，已终止。请检查网络（代理走 git 配置或环境变量，本工具不绑定代理）。" % timeout_s)
        return EXIT_TIMEOUT
    except OSError as exc:
        warn("无法执行 git：%s" % exc)
        return EXIT_IO
    out = (proc.stdout + proc.stderr).decode("utf-8", errors="replace").strip()
    if out:
        say(out)
    if proc.returncode != 0:
        warn("git pull 失败（退出码 %d）。请先在本体目录手工解决（冲突/网络/认证）后重试。" % proc.returncode)
        return proc.returncode
    new_ver = upstream_version(root) or "未知"
    if new_ver == old_ver:
        say("本体已是最新：v%s（无版本变化）。" % old_ver)
    else:
        say("本体已更新：v%s → v%s。" % (old_ver, new_ver))
        say("提示：技能/钩子在本会话中可能仍是旧载入；新开会话后生效。")
        say("如需把当前项目契约同步到新版本，接着执行：tsc sync --project <项目根>")
    return EXIT_OK


# --------------------------------------------------------------------------- #
# rollback：恢复上一次 install/sync 写盘之前的项目契约状态
# --------------------------------------------------------------------------- #
def cmd_rollback(proj_root):
    proj_root = Path(proj_root)
    manifest_path = proj_root / AGENTS_DIR / BACKUP_DIRNAME / "manifest.json"
    if not manifest_path.is_file():
        warn("没有可回滚的记录（%s 不存在）。" % manifest_path)
        warn("rollback 只能撤销最近一次 install/sync 的写入。")
        return EXIT_STATE
    try:
        manifest = json.loads(read_text(manifest_path))
    except (ValueError, OSError) as exc:
        warn("回滚清单损坏，拒绝盲目恢复：%s" % exc)
        return EXIT_IO
    problems = []
    restored = []
    for entry in reversed(manifest.get("files", [])):
        target = proj_root / entry["path"]
        try:
            if entry["action"] == "create":
                if target.is_file():
                    target.unlink()
            else:
                write_text_atomic(target, entry["content"])
            restored.append((entry["action"], entry["path"]))
        except (OSError, KeyError) as exc:
            problems.append("%s（%s）" % (entry.get("path", "?"), exc))
    try:
        shutil.rmtree(manifest_path.parent)
    except OSError as exc:
        problems.append("清理备份目录失败（%s）" % exc)
    say("已回滚到 %s 之前的状态（契约版本 %s）。" % (
        manifest.get("backed_up_at", "上次同步"), manifest.get("contract_version", "未知")))
    for action, rel in restored:
        say("  %s %s" % ("已删除（上次新建）" if action == "create" else "已还原", rel))
    if problems:
        for p in problems:
            warn("  回滚未彻底，请人工检查：%s" % p)
        return EXIT_IO
    say("注意：回滚只撤销最近一次 install/sync；之后项目里的手工修改会被还原内容覆盖。")
    return EXIT_OK


# --------------------------------------------------------------------------- #
# status / doctor
# --------------------------------------------------------------------------- #
def cmd_status(proj_root, upstream, as_json=False):
    proj_root = Path(proj_root)
    ownership = contract_ownership(proj_root)
    up_ver = upstream_version(upstream) if upstream is not None else None
    data = {
        "project": str(proj_root),
        "installed": (proj_root / AGENTS_DIR).is_dir() and (proj_root / AGENTS_MD).is_file(),
        "ownership": ownership,
        "contract_version": local_version(proj_root),
        "upstream": str(upstream) if upstream else None,
        "upstream_version": up_ver,
        "provenance": read_source_record(proj_root),
        "node_project": is_node_project(proj_root),
        "report": [],
    }

    def line(label, value):
        data["report"].append("%s：%s" % (label, value))

    line("项目根", proj_root)
    line("是否已接入", "是" if data["installed"] else "否（先跑 install）")
    line("所有权", OWNERSHIP_LABEL[ownership])
    line("当前版本", data["contract_version"] or "（无 .agents/VERSION）")
    line("上游版本", "%s（%s）" % (up_ver or "未知", upstream) if upstream else "未指定")
    prov = data["provenance"]
    if prov:
        line("来源记录（仅 provenance，不参与选源）", "%s v%s @ %s" % (
            prov.get("source"), prov.get("version", "?"), prov.get("installed_at", "?")))
    agents_md = proj_root / AGENTS_MD
    if agents_md.is_file():
        block = section2_text(read_text(agents_md))
        if block is None:
            line("§2 是否填好", "找不到 §2 章节（AGENTS.md 不完整，先人工修复）")
        elif PLACEHOLDER in block:
            line("§2 是否填好", "否，仍有 %s 占位" % PLACEHOLDER)
        else:
            line("§2 是否填好", "是")
    project_py = proj_root / AGENTS_DIR / PROJECT_FILE
    line("门禁可跑", "是" if project_py.is_file() else "否（缺 .agents/project.py）")
    legacy = detect_legacy(proj_root)
    if legacy:
        line("检测到旧结构（跑 sync 会自动搬进 .agents/）", "、".join(legacy))
    stale = detect_skill_only_leftovers(proj_root)
    if stale:
        line("冗余执行逻辑（可自行删除，不影响功能）", "、".join(stale))
    if as_json:
        say(json.dumps(data, ensure_ascii=False, indent=2))
        return EXIT_OK
    for entry in data["report"]:
        say(entry)
    return EXIT_OK


def cmd_doctor(proj_root, upstream, as_json=False):
    proj_root = Path(proj_root)
    checks = []  # (名称, ok|warn|fail, 说明)

    def add(name, state, detail=""):
        checks.append((name, state, detail))

    add("解释器", "ok", "%s（Python %s）" % (sys.executable, sys.version.split()[0]))

    up_ver = None
    if upstream is None:
        add("上游来源", "fail", "无法定位（本脚本应位于 <插件根>/scripts/ 下）")
    else:
        missing = validate_upstream(upstream)
        up_ver = upstream_version(upstream)
        if missing:
            add("上游来源", "fail", "%s 不完整，缺少：%s" % (upstream, "、".join(missing)))
        else:
            add("上游来源", "ok", "%s（v%s）" % (upstream, up_ver))
    if (upstream_root() / ".git").exists():
        add("本体更新通道", "ok", "git 安装（tsc update 可直接 pull）")
    else:
        add("本体更新通道", "warn", "非 git 安装：本体更新走宿主插件市场（tsc update 不适用）")

    installed = (proj_root / AGENTS_MD).is_file()
    ownership = contract_ownership(proj_root)
    if not installed:
        add("项目接入", "fail", "未接入（先跑 install）")
    elif ownership == "foreign":
        add("项目接入", "fail", "AGENTS.md 为外部文件且未接管（接管须 install --force）")
    else:
        add("项目接入", "ok", OWNERSHIP_LABEL[ownership])

    contract_ver = local_version(proj_root)
    if upstream is not None and up_ver:
        if contract_ver is None:
            add("契约版本", "fail", "缺 .agents/VERSION（跑 sync 补齐）")
        elif contract_ver != up_ver:
            add("契约版本", "warn", "项目 v%s 落后上游 v%s（跑 sync 跟进）" % (contract_ver, up_ver))
        else:
            add("契约版本", "ok", "v%s（与上游一致）" % contract_ver)

    agents_md = proj_root / AGENTS_MD
    section2_filled = False
    if agents_md.is_file():
        block = section2_text(read_text(agents_md))
        if block is None:
            add("§2 配置", "fail", "AGENTS.md 找不到 §2 章节")
        elif PLACEHOLDER in block:
            add("§2 配置", "fail", "仍有 %s 占位（按 BOOTSTRAP 探测填充）" % PLACEHOLDER)
        else:
            add("§2 配置", "ok", "已填充")
            section2_filled = True

    project_py = proj_root / AGENTS_DIR / PROJECT_FILE
    if not project_py.is_file():
        add("门禁命令源", "fail", "缺 .agents/project.py")
    elif section2_filled:
        comparable, mismatch = _config_mismatches(proj_root)
        if not comparable:
            add("§2 ⇆ project.py", "fail", "；".join(mismatch))
        elif mismatch:
            add("§2 ⇆ project.py", "fail", "不一致：%s" % "、".join(mismatch))
        else:
            add("§2 ⇆ project.py", "ok", "同源一致")

    node = is_node_project(proj_root)
    if node:
        npm = shutil.which("npm")
        add("项目类型", "ok" if npm else "warn",
            "Node/JS（package.json）；commitlint 已部署" + ("" if npm else "，但 npm 不在 PATH（commitlint 钩子无法本地运行，CI 兜底）"))
    else:
        add("项目类型", "ok", "非 Node 项目：不部署 commitlint，零 npm 依赖")

    enforce_state = []
    for rel_src, rel_dst in ENFORCE_DEPLOY.items():
        if rel_src in NODE_ONLY_ENFORCE and not node:
            continue
        dst = proj_root / rel_dst
        if not dst.is_file():
            enforce_state.append("%s 缺失" % rel_dst)
        elif not has_marker(read_text(dst), MANAGED_MARKER):
            enforce_state.append("%s 已被项目接管（不自动更新）" % rel_dst)
    if enforce_state:
        add("执法包", "warn", "；".join(enforce_state))
    else:
        add("执法包", "ok", "齐备且托管")

    prov = read_source_record(proj_root)
    if prov:
        add("来源记录", "ok", "%s（仅 provenance）" % prov.get("source"))

    failed = [c for c in checks if c[1] == "fail"]
    warned = [c for c in checks if c[1] == "warn"]
    verdict = "ready" if not failed else "not-ready"
    data = {
        "project": str(proj_root),
        "verdict": verdict,
        "checks": [{"name": n, "state": s, "detail": d} for n, s, d in checks],
    }
    if as_json:
        say(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        for name, state, detail in checks:
            mark = {"ok": "✅", "warn": "🟡", "fail": "❌"}[state]
            say("%s %s%s" % (mark, name, ("：" + detail) if detail else ""))
        say("结论：%s（%d 项通过，%d 项警告，%d 项失败）" % (
            verdict, len(checks) - len(failed) - len(warned), len(warned), len(failed)))
    return EXIT_OK if verdict == "ready" else EXIT_STATE


def _config_mismatches(proj_root):
    """§2 与 project.py 同源校验（供 doctor 用）。返回 (是否可比较, mismatch 列表)。"""
    cfg = load_project_config(proj_root)
    if cfg is None:
        return False, ["project.py 无法加载"]
    table = read_section2_values(proj_root)
    if table is None:
        return False, ["无法从 AGENTS.md 读出 §2 表格"]
    mismatch = []
    for key in ("FMT_CHECK_CMD", "LINT_CMD", "TEST_CMD", "BUILD_CMD"):
        if key not in cfg:
            mismatch.append(key)
            continue
        expected = normalize_value(cfg.get(key))
        actual = normalize_value(unescape_cell(table.get(key, "")))
        if expected != actual:
            mismatch.append(key)
    return True, mismatch


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def build_parser():
    parser = argparse.ArgumentParser(prog="tsc", description="契约分发与门禁")
    parser.add_argument(
        "command",
        nargs="?",
        default=None,
        choices=[None, "status", "install", "sync", "update", "verify", "check-config", "doctor", "rollback"],
        help="要执行的子命令",
    )
    parser.add_argument("--source", dest="source", default=None, help="显式上游（本地插件目录）")
    parser.add_argument("--from", dest="source", default=None, help=argparse.SUPPRESS)  # 旧名兼容
    parser.add_argument("--project", default=None, help="目标项目根（默认当前目录）")
    parser.add_argument("--dry-run", action="store_true", help="只报告，不写文件")
    parser.add_argument("--force", action="store_true", help="install 时显式接管外部 AGENTS.md")
    parser.add_argument("--timeout", type=int, default=None, help="门禁命令/网络操作超时秒数（默认 %d）" % DEFAULT_TIMEOUT_S)
    parser.add_argument("--json", action="store_true", help="status/doctor 输出 JSON")
    parser.add_argument("--version", action="store_true", help="打印本体版本")
    return parser


def main(argv=None):
    _init_stdout()
    args = build_parser().parse_args(argv)
    if args.version:
        say(upstream_version(upstream_root()) or "unknown")
        return EXIT_OK
    if args.command is None:
        build_parser().print_usage()
        return EXIT_STATE
    try:
        return _dispatch(args)
    except OSError as exc:
        # 顶层兜底：读盘 / 定位上游等未捕获的 IO 异常按契约归一为退出码 2
        warn("执行失败（IO / 权限 / 文件占用）：%s" % exc)
        return EXIT_IO


def _dispatch(args):
    if args.project:
        proj_root = Path(normalize_path_arg(args.project)).expanduser().resolve()
    else:
        proj_root = Path.cwd()

    if args.command == "update":
        return cmd_update(args.timeout if args.timeout else DEFAULT_TIMEOUT_S)
    if args.command == "rollback":
        return cmd_rollback(proj_root)

    upstream = None
    if args.command in ("status", "install", "sync", "doctor"):
        upstream = find_upstream(args.source)
        missing = validate_upstream(upstream)
        if missing:
            warn("上游不完整，缺少：%s" % "、".join(missing))
            warn("上游路径：%s" % upstream)
            return EXIT_STATE

    if args.command == "status":
        return cmd_status(proj_root, upstream, as_json=args.json)
    if args.command == "doctor":
        return cmd_doctor(proj_root, upstream, as_json=args.json)
    if args.command == "verify":
        return cmd_verify(proj_root, timeout_override=args.timeout)
    if args.command == "check-config":
        return cmd_check_config(proj_root)

    if not proj_root.is_dir():
        warn("目标项目目录不存在：%s" % proj_root)
        return EXIT_STATE

    if args.command == "sync" and args.force:
        warn("sync 不接受 --force：接管外部 AGENTS.md 只能通过 install --force 显式完成。")
        return EXIT_STATE
    if args.command == "install" and args.force:
        ownership = contract_ownership(proj_root)
        if ownership != "foreign":
            warn("--force 仅用于接管外部 AGENTS.md；本项目%s，无需 force。" % (
                "尚未接入" if ownership == "none" else "已是 TSC 托管"))
            return EXIT_STATE

    return do_apply(proj_root, upstream, args.dry_run, args.force)


if __name__ == "__main__":
    sys.exit(main())
