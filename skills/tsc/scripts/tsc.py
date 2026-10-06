#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tsc —— 契约分发与门禁的唯一核心脚本（常驻技能 scripts/ 目录）。

用法（脚本留在技能目录，用 --project 指定目标项目）：
    python3 <技能根>/scripts/tsc.py status       --project <项目根>
    python3 <技能根>/scripts/tsc.py install     [--force] --project <项目根>
    python3 <技能根>/scripts/tsc.py sync         --project <项目根>
    python3 <技能根>/scripts/tsc.py update      [--timeout <秒>]
    python3 <技能根>/scripts/tsc.py verify      [--timeout <秒>] --project <项目根>
    python3 <技能根>/scripts/tsc.py check-config --project <项目根>
    python3 <技能根>/scripts/tsc.py doctor      [--json] --project <项目根>
    python3 <技能根>/scripts/tsc.py rollback     --project <项目根>

    `--project` 省略时取当前工作目录，因此"cd 到项目里再跑"也成立。

命令边界（两类升级严格分开，不要混为一谈）：
    update   只更新 TSC 技能本体（git pull；非 git 安装副本走宿主更新机制）
    sync     只更新当前项目契约（来源恒为"当前已安装的本体"，绝不读项目 .source）
    install  首次接入；目标项目已有外部 AGENTS.md 时必须 --force 显式接管
    doctor   只读诊断，给出 ready / not-ready 结论
    rollback 恢复上一次 install/sync 写盘之前的项目契约状态

通用参数：
    --source <路径>  显式上游（本地技能目录），默认=本脚本所在技能根
    --from <路径>    同 --source（旧名兼容）
    --project <路径> 目标项目根（默认当前目录）
    --dry-run        只报告将发生的变化，不写任何文件（完全零写盘）
    --force          install 时确认接管外部 AGENTS.md
    --timeout <秒>   verify 每条门禁命令 / update 网络操作的超时（默认 600）
    --json           status / doctor 输出 JSON
    --version        打印本体版本

退出码：
    0    成功 / 已是最新
    1    需要人工处理（§2 结构变更、外部 AGENTS.md 未接管、§2 与 project.py 不一致、
         update 的 git 操作失败需人工解决）
    2    IO / 编码 / 权限错误（含事务失败已自动回滚、回滚清单损坏/未彻底）
    3    状态非法（缺 §2、缺 VERSION、上游无效、门禁全未配置、无可回滚记录、
         project.py 含白名单外的可执行结构、路径越界、rollback/update 传 --dry-run）
    124  门禁命令超时被终止

设计约束：
    - 零第三方依赖，仅用标准库。
    - 所有文本读写强制 UTF-8 与 LF，避免 Windows 默认 CRLF 破坏行数门禁口径。
    - 上游来源只接受本地路径（已安装的本体本身就是上游）；不联网（update 除外）。
    - install / sync 是**单事务**：先算完整 mutation plan，备份清单在实际写盘前
      先落盘为临时文件，写入 / 旧结构迁移任一步失败自动恢复原状，全部成功后才
      以 os.replace 提交备份清单（committed）；失败事务不留半成品备份。
    - 所有项目写入与回滚路径统一过 safe_project_path：拒绝绝对路径、`..`、
      symlink 逃逸；rollback 在第一次写入前完整校验 manifest，绝不恢复一半。
    - .agents/project.py 一律 AST 安全解析（白名单常量），绝不 exec。
    - 绝不自动删除文件；旧结构只做"移动 + 提示"（rollback 删除的仅限上次事务
      新建的文件）。
    - 执法包（enforcement）默认随 install 落盘；带 tsc-managed 标记的才托管更新。
    - commitlint 是**可选执法适配层**：仅 Node 项目且项目自己没有提交规范配置时
      才部署；核心 TSC 不依赖 Node，纯 Python 项目绝不引入 npm 依赖。
"""

import argparse
import ast
import json
import os
import re
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

# 插件/技能布局：本脚本在 <技能根>/scripts/ 下，上游根即其上一级。
SCRIPT_SUBDIR = "scripts"
TEMPLATE_AGENTS = "templates/AGENTS.md"
TEMPLATE_PROJECT_EXAMPLE = "templates/project.example.py"
ENFORCE_SUBDIR = "templates/enforcement"

# 上游（技能本体）必需产物清单：install/sync/status/doctor 都按它做完整校验。
# 缺任一必要文件 => 拒绝开始，绝不产生项目写盘（防"残缺上游"半升级）。
REQUIRED_UPSTREAM = [
    "SKILL.md",
    VERSION_FILE,
    SCRIPT_SUBDIR + "/tsc.py",
    SCRIPT_SUBDIR + "/structure_guard.py",
    SCRIPT_SUBDIR + "/bracket_lint.py",
    SCRIPT_SUBDIR + "/install_hook.py",
    TEMPLATE_AGENTS,
    TEMPLATE_PROJECT_EXAMPLE,
    ENFORCE_SUBDIR + "/gate.yml",
    ENFORCE_SUBDIR + "/.pre-commit-config.yaml",
    ENFORCE_SUBDIR + "/commitlint.config.js",
    ENFORCE_SUBDIR + "/README.md",
    "references/AUDIT-SPEC.md",
    "references/BOOTSTRAP.md",
    "commands/tsc.md",
    "commands/tsc-update.md",
    "commands/tsc-status.md",
    "commands/tsc-sync.md",
]
VERSION_FORMAT = re.compile(r"^\d+\.\d+\.\d+$")

# 执法包模板 → 落地位置。commitlint 是 Node 项目的可选适配层（见 commitlint_wanted）。
ENFORCE_DEPLOY = {
    ENFORCE_SUBDIR + "/gate.yml": ".github/workflows/gate.yml",
    ENFORCE_SUBDIR + "/.pre-commit-config.yaml": ".pre-commit-config.yaml",
    ENFORCE_SUBDIR + "/commitlint.config.js": "commitlint.config.js",
    SCRIPT_SUBDIR + "/structure_guard.py": ".agents/structure_guard.py",
    SCRIPT_SUBDIR + "/bracket_lint.py": ".agents/bracket_lint.py",
}
# 只属于 Node/JS 项目的执法件（且项目自己没有提交规范配置时才部署）。
NODE_ONLY_ENFORCE = {ENFORCE_SUBDIR + "/commitlint.config.js"}
NODE_MANIFEST = "package.json"
# 项目已有提交规范配置的任何一种形态 => 尊重现状，不部署 TSC 的 commitlint 适配层。
COMMITLINT_CONFIG_FILES = (
    "commitlint.config.js", "commitlint.config.cjs", "commitlint.config.mjs",
    "commitlint.config.json", ".commitlintrc", ".commitlintrc.json",
    ".commitlintrc.js", ".commitlintrc.cjs", ".commitlintrc.mjs",
    ".commitlintrc.yml", ".commitlintrc.yaml",
)
PM_LOCKFILES = {
    "pnpm-lock.yaml": "pnpm",
    "yarn.lock": "yarn",
    "bun.lockb": "bun",
}

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

# --------------------------------------------------------------------------- #
# pre-commit 结构门禁钩子的解释器名：部署时按**本机**探测填，不写死模板。
#
# 为什么必须这样（2026-09-23 对照实验，四种写法逐一实测）：
#   - pre-commit 的 `repo: local` 里，只有 `language: system` 能跑项目内脚本；
#     system 语言的 entry 首令牌**完全靠系统 PATH 解析**。而解释器名各平台不齐：
#     macOS / 多数 Linux 只有 `python3`，Windows 常见只有 `python`。写死任何一个，
#     另一平台就是 `Executable 'pythonX' not found` → 提交被堵住。
#   - `language: python` 看着能跨平台，实测**不可用**：pre-commit 会先对项目根
#     执行 `pip install .`，没有 setup.py / pyproject.toml 的项目直接
#     `ERROR: Directory '.' is not installable` → 所有平台一起坏。
#   - `language: script` + 项目内 sh 启动器同样不可用：Windows 上报
#     `Executable '/bin/sh' not found`。
# 结论：模板只能给个默认值，真正可用的名字由 install/sync 时探测后填进落盘件。
# 副作用是"在 A 机器部署、换到 B 平台用"会残留 A 的名字——重跑一次 sync 即校正；
# sync 的内容比对按同一套渲染逻辑算，所以能自愈。
PRE_COMMIT_INTERPRETERS = ("python3", "python")   # 探测顺序 = 优先级
PRE_COMMIT_GUARD_ENTRY = ("python3 .agents/structure_guard.py "
                          "--staged --strict --allow-missing-tools "
                          "--quiet --color never")


def pick_precommit_interpreter():
    """挑一个本机能解析到的解释器名；都没有则 None（保持模板默认）。"""
    for name in PRE_COMMIT_INTERPRETERS:
        if shutil.which(name):
            return name
    return None

DEFAULT_TIMEOUT_S = 600

# 门禁超时可在项目 project.py 里按步覆盖：GATE_TIMEOUTS = {"TEST_CMD": 300}
GATE_TIMEOUTS_KEY = "GATE_TIMEOUTS"
# project.py 里允许读取的配置白名单（AST 解析，绝不 exec）。
CONFIG_KEYS = ("FMT_CHECK_CMD", "LINT_CMD", "TEST_CMD", "BUILD_CMD", "GATE_TIMEOUTS")

PLACEHOLDER = "[自动填充]"

SKILL_ONLY_LEFTOVERS = [
    # 旧版本曾复制进项目的执行逻辑；现已统一由技能目录提供，只提示、不删除。
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
# 路径安全：所有项目写入 / 回滚路径的唯一入口
# --------------------------------------------------------------------------- #
class UnsafeProjectPath(Exception):
    """路径越出项目根、含 ..、是绝对路径、或经 symlink 逃逸/重定向。"""


def safe_project_path(proj_root, rel):
    """把"项目根相对路径"安全解析为绝对路径。

    规则（全部满足才放行）：
    - 必须是非空相对路径；拒绝绝对路径（含 Windows 盘符）；
    - 拒绝任何 `..` 段（含嵌套、`..` 变体）；
    - resolve 后必须仍在项目根内（堵死 symlink/junction 指向项目外的逃逸）；
    - 从项目根到目标的任何路径组件都不得是 symlink（受管理路径
      `.agents` / `AGENTS.md` / `.github/workflows/*` 等绝不允许被 symlink 重定向）。
    返回 (未解析目标, resolve 后绝对路径)；不安全时抛 UnsafeProjectPath。
    """
    rel = str(rel)
    unified = rel.replace("\\", "/")
    if not unified:
        raise UnsafeProjectPath("空路径")
    if unified.startswith("/") or re.match(r"^[A-Za-z]:", unified):
        raise UnsafeProjectPath("绝对路径不允许：%s" % rel)
    parts = [seg for seg in unified.split("/") if seg not in ("", ".")]
    if not parts:
        raise UnsafeProjectPath("路径没有实际组件：%s" % rel)
    if any(seg == ".." for seg in parts):
        raise UnsafeProjectPath("路径含 `..`：%s" % rel)
    root = Path(proj_root).resolve()
    target = root.joinpath(*parts)
    resolved = target.resolve()
    if resolved != root and root not in resolved.parents:
        raise UnsafeProjectPath(
            "resolve 后越出项目根（疑似 symlink 逃逸）：%s -> %s" % (rel, resolved))
    for depth in range(1, len(parts) + 1):
        ancestor = root.joinpath(*parts[:depth])
        # is_symlink 只认真正的符号链接；Windows junction 要靠 realpath 对比抓——
        # 两种"路径组件被重定向"的形态都不允许出现在受管理写入路径上
        real = os.path.normcase(os.path.realpath(str(ancestor)))
        if ancestor.is_symlink() or real != os.path.normcase(str(ancestor)):
            raise UnsafeProjectPath(
                "路径组件 %s 是 symlink/junction，拒绝经其写入（%s）" % (
                    "/".join(parts[:depth]), rel))
    return target, resolved


def _ensure_parent(path):
    """确保父目录存在，返回**本次新建**的目录列表（浅→深，供事务回滚逐层删除）。"""
    path = Path(path)
    to_make, cursor = [], path.parent
    while not cursor.exists():
        to_make.append(cursor)
        cursor = cursor.parent
    if to_make:
        path.parent.mkdir(parents=True, exist_ok=True)
    return list(reversed(to_make))  # 浅→深


def _remove_empty_dirs_quietly(dirs):
    """逆序（深→浅）删除空目录；遇到非空/失败即停（父目录必然也非空）。"""
    for d in reversed(dirs):
        try:
            d.rmdir()
        except OSError:
            return


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
# 上游定位：显式 --source > 当前已安装本体（本脚本所在技能根）。
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
    """完整校验上游：必需产物存在性 + 关键内容格式。返回问题列表（空 = 通过）。

    残缺上游（缺任一必要文件 / VERSION 格式非法 / 模板缺 §2 或所有权标记）
    一律拒绝 install/sync，绝不产生项目写盘。
    """
    root = Path(root)
    problems = [name for name in REQUIRED_UPSTREAM if not (root / name).is_file()]
    if VERSION_FILE in problems:
        return problems  # 连版本文件都没有，内容检查无意义
    ver = read_text(root / VERSION_FILE).strip()
    if not VERSION_FORMAT.match(ver):
        problems.append("%s 版本格式非法：%r（应为 x.y.z）" % (VERSION_FILE, ver))
    tpl = root / TEMPLATE_AGENTS
    if tpl.is_file():
        text = read_text(tpl)
        if section2_span(text) is None:
            problems.append("%s 缺少 §2 章节" % TEMPLATE_AGENTS)
        if CONTRACT_MARKER_LINE not in text:
            problems.append("%s 缺少所有权标记 %s" % (TEMPLATE_AGENTS, CONTRACT_MARKER_LINE))
    return problems


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
# AGENTS.md 所有权：marker 决定一切；legacy 必须凑齐 ≥2 个独立 TSC 历史特征
# --------------------------------------------------------------------------- #
def _tsc_version_evidence(proj_root):
    """特征 A：.agents/VERSION 是合法的历史 TSC 版本号（x.y.z）。"""
    vf = Path(proj_root) / AGENTS_DIR / VERSION_FILE
    if not vf.is_file():
        return False
    return bool(VERSION_FORMAT.match(read_text(vf).strip()))


def _tsc_deployment_evidence(proj_root):
    """特征 B：除版本文件外的独立 TSC 部署痕迹（任一命中即可）。

    单凭 `.agents/VERSION` 存在绝不认定 legacy——外部项目完全可能恰好有同名
    文件。这里只认 TSC 自己留下的、外部项目不会"恰好"齐备的痕迹：
    - .agents/.source（TSC install 必写的 provenance）；
    - 根目录残留旧版契约文件（AUDIT-SPEC.md / BOOTSTRAP.md，v3 布局）；
    - .agents/ 里带 tsc-managed 标记的落盘检查器（structure_guard / bracket_lint）。
    §2 表格形状**不算**证据——长得像 TSC 的表格谁都能写，碰巧撞上不算部署。
    """
    proj_root = Path(proj_root)
    agents_dir = proj_root / AGENTS_DIR
    if (agents_dir / SOURCE_FILE).is_file():
        return True
    if any((proj_root / n).is_file() for n in LEGACY_FILE_ENTRIES):
        return True
    for name in ("structure_guard.py", "bracket_lint.py"):
        p = agents_dir / name
        if p.is_file():
            try:
                if has_marker(read_text(p), MANAGED_MARKER):
                    return True
            except OSError:
                continue
    return False


def contract_ownership(proj_root):
    """判定项目 AGENTS.md 的所有权。

    返回：
        none        没有 AGENTS.md（全新接入）
        managed     带"整行" tsc-managed-contract 标记（TSC 托管；正文提及该字符串不算）
        legacy      无标记，但凑齐 ≥2 个独立 TSC 历史特征（合法历史版本号 + 部署痕迹）；
                    只允许一次性升级：重建时补上标记
        foreign     外部项目自己的 AGENTS.md（无标记、TSC 证据不足）——默认只读，
                    不自动接管；凑不齐两个特征时一律按 foreign 处理
    """
    agents_md = Path(proj_root) / AGENTS_MD
    if not agents_md.is_file():
        return "none"
    if has_marker(read_text(agents_md), CONTRACT_MARKER):
        return "managed"
    if _tsc_version_evidence(proj_root) and _tsc_deployment_evidence(proj_root):
        return "legacy"
    return "foreign"


OWNERSHIP_LABEL = {
    "none": "未接入",
    "managed": "TSC 托管（%s）" % CONTRACT_MARKER_LINE,
    "legacy": "旧版 TSC 部署（≥2 项 TSC 历史特征，首次 sync 会补上标记）",
    "foreign": "外部 AGENTS.md（非 TSC 托管，默认只读）",
}


# --------------------------------------------------------------------------- #
# Node/JS 探测：commitlint 只是可选执法适配层，绝不默认引入 npm 体系
# --------------------------------------------------------------------------- #
def is_node_project(proj_root):
    return (Path(proj_root) / NODE_MANIFEST).is_file()


def commitlint_wanted(proj_root):
    """是否应部署 TSC 的 commitlint 适配层。返回 (是否部署, 原因说明)。

    仅当：项目是 Node 项目（有 package.json），**且**项目自己没有**其它形态**的
    提交规范配置（.commitlintrc* 等）时才部署。`commitlint.config.js` 本身不在
    这里判：它是执法包的一员，归属（托管 / legacy 升级 / 项目已接管）由
    _enforce_actions 的三态规则统一管辖——被项目接管的文件走"内容已被项目改过"
    的显式跳过，不会被这里静默略过。
    """
    if not is_node_project(proj_root):
        return False, "非 Node 项目"
    proj_root = Path(proj_root)
    for name in COMMITLINT_CONFIG_FILES:
        if name == "commitlint.config.js":
            continue  # 执法包三态规则管辖（见 docstring）
        if (proj_root / name).is_file():
            return False, "项目已有提交规范配置 %s" % name
    return True, "Node 项目且无自有提交规范配置"


def detect_lockfile_pm(proj_root):
    """项目已有的包管理器（按锁文件探测）；非 npm 返回名字，探测不到返回 None。"""
    for lockfile, pm in PM_LOCKFILES.items():
        if (Path(proj_root) / lockfile).is_file():
            return pm
    return None


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


# gate.yml 的 branches 渲染：简单分支名保持原样（[main]），含逗号/]/#/{} /空格/
# 引号等字符的合法分支名必须走 YAML 单引号流序列（' 内 '' 转义），绝不裸插值。
_SIMPLE_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def render_branches_entry(branch):
    """把分支名渲染成 YAML flow sequence（branches: [...]）。"""
    if _SIMPLE_BRANCH_RE.match(branch):
        return "branches: [%s]" % branch
    return "branches: ['%s']" % branch.replace("'", "''")


def _branch_variants(branch):
    """debranch 用：同一分支名在落盘件里可能出现过的全部写法。"""
    if _SIMPLE_BRANCH_RE.match(branch):
        return ("branches: [%s]" % branch,)
    return ("branches: ['%s']" % branch.replace("'", "''"),)


def enforce_template_content(rel_src, proj_root, upstream, merged_agents_text):
    """算出某执法模板落在该项目里的最终内容；模板不存在返回 None。"""
    src = Path(upstream) / rel_src
    if not src.is_file():
        return None
    content = read_text(src)
    main_branch = section2_value(section2_text(merged_agents_text), "主干分支")
    if main_branch:
        main_branch = main_branch.strip().strip("`").strip()
        if PLACEHOLDER in main_branch or main_branch in ("无", "—", ""):
            main_branch = None  # §2 占位或未填（如非 git 项目）→ 保持模板默认 [main]
    if rel_src.endswith("gate.yml") and main_branch:
        content = content.replace("branches: [main]", render_branches_entry(main_branch))
    if not is_node_project(proj_root):
        # 非 Node 项目：剔除 Node 专属区块（commitlint 整文件已在部署清单里排除）
        content = strip_node_regions(content)
    if rel_src.endswith(".pre-commit-config.yaml"):
        picked = pick_precommit_interpreter()
        if picked and picked != PRE_COMMIT_INTERPRETERS[0]:
            # 本机只认 `python`（典型 Windows）→ 把 entry 首令牌换成能解析的那个名
            content = content.replace(
                PRE_COMMIT_GUARD_ENTRY,
                picked + PRE_COMMIT_GUARD_ENTRY[len(PRE_COMMIT_INTERPRETERS[0]):],
            )
    return content


# --------------------------------------------------------------------------- #
# 旧结构迁移（只移动，不删除；进入同一事务）
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


def plan_legacy_moves(proj_root):
    """把旧布局迁移算成 move 计划（不写盘）。返回 (moves, 同名冲突残留)。

    moves: [(相对根的源, 相对根的目标)]；目标已存在的条目不搬、进残留列表。
    搬移发生在事务里：失败自动逆序搬回，不留半截迁移。
    """
    proj_root = Path(proj_root)
    moves, leftover = [], []
    for name in detect_legacy(proj_root):
        src = proj_root / name
        dst = proj_root / AGENTS_DIR / name
        if dst.exists():
            leftover.append(src)
            continue
        moves.append((name, (Path(AGENTS_DIR) / name).as_posix()))
    return moves, leftover


def detect_skill_only_leftovers(proj_root):
    """项目 .agents/ 里残留的执行逻辑（现由技能目录统一提供）。只用于提示，不删除。

    扫描目标本身就是上游/技能目录时返回空——那里的逻辑是正本，不是冗余。
    """
    proj_root = Path(proj_root)
    try:
        if proj_root.resolve() == upstream_root().resolve():
            return []
    except OSError:
        pass
    agents_dir = proj_root / AGENTS_DIR
    return [n for n in SKILL_ONLY_LEFTOVERS if (agents_dir / n).exists()]


# --------------------------------------------------------------------------- #
# 同步主流程
# --------------------------------------------------------------------------- #
def collect_payload(upstream):
    """需要分发到项目的文件：键为相对项目根的路径，值为上游源文件。

    只分发"必须躺在项目里"的东西：版本号一个。执行逻辑（tsc.py / AUDIT-SPEC /
    BOOTSTRAP / verify.* / test / 执法包模板原件）一律留在技能目录，不往项目里复制。
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


def is_self_bootstrap(proj_root, upstream):
    """目标项目就是上游本体的宿主仓库（母版/技能仓库自举）。

    两种安装形态都表示"这个项目就是 TSC 自己的仓库"：
    - 上游 == 项目根                 → v4.0.0 及更早的"技能就在仓库根"布局；
    - 上游 == <项目根>/skills/tsc/   → 自包含技能布局（技能目录是仓库的子目录）。

    自举时不往根目录铺生效件——模板原件已在技能 templates/ 下，再铺一份就是重复真身。
    因此凡是"执法包是否齐备"的判定都必须先过这一关：`_enforce_actions` 靠它跳过落盘，
    `cmd_doctor` 靠它跳过缺失告警。两边口径必须一致，否则母版自检永远误报（A-03）。

    注意判据不能用"上游在项目之内"：宿主把技能装进项目里的 `.claude/skills/` 时也满足
    "之内"，那属于正常的待接入项目，必须照常铺执法包。
    """
    if upstream is None:
        return False
    try:
        proj = os.path.normcase(str(Path(proj_root).resolve()))
        up = os.path.normcase(str(Path(upstream).resolve()))
        up_skill = os.path.normcase(str((Path(proj_root) / "skills" / "tsc").resolve()))
    except OSError:
        return False
    return proj == up or up == up_skill


def git_worktree_of(path):
    """path 所属 git 仓库的工作树根；不在 git 工作树里则 None。

    两种安装形态都要认：技能目录自身是 git 副本（宿主技能目录里 clone 的），
    或技能目录是某个 git 仓库的子目录（<仓库根>/skills/tsc/）。只查
    `<技能根>/.git` 会把后者误判成"非 git 安装"，进而谎报 `tsc update` 不可用。
    """
    d = Path(path).resolve()
    for cand in (d, *d.parents):
        if (cand / ".git").exists():
            return cand
    return None


def _enforce_actions(proj_root, upstream, merged_agents_text):
    """算出执法包落盘动作，不写任何文件（判定单源，供部署与早退检查共用）。

    归属规则（MANAGED_MARKER = "tsc-managed"，须为整行注释声明，正文提及不算）：
    - 项目文件带标记 → 技能托管：以上游模板为准，内容不同就更新；
    - 不带标记但正文与模板一致（忽略标记行与 gate.yml 分支名）→ 旧版部署
      的文件，一次性升级为带标记的托管版；
    - 不带标记且正文不同 → 项目已接管，永不覆盖，只提示。
    - commitlint.config.js 只在"Node 项目且项目自己没有提交规范配置"时部署；
      .pre-commit-config.yaml 的 Node 专属区块在非 Node 项目中剔除。
    返回 (新部署, 已更新, 跳过)。
    """
    proj_root = Path(proj_root)
    if is_self_bootstrap(proj_root, upstream):
        # 母版/技能目录自举：模板原件已在 templates/，不往自己根目录铺生效件
        return [], [], []
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
        if main_branch:
            main_branch = main_branch.strip().strip("`").strip()
            if PLACEHOLDER in main_branch or main_branch in ("无", "—", ""):
                main_branch = None
        if main_branch:
            for variant in _branch_variants(main_branch):
                text = text.replace(variant, "branches: [main]")
        return text

    for rel_src, rel_dst in ENFORCE_DEPLOY.items():
        if rel_src in NODE_ONLY_ENFORCE and not commitlint_wanted(proj_root)[0]:
            continue  # 非目标项目不部署 commitlint（可选适配层）
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

        # 旧版部署的一次性迁移：正文一致（忽略标记行/分支名/Node 区块差异）→ 升级为托管版。
        # 两侧都剥 Node 区块再比——只剥右侧会让 Node 项目的旧部署文件永远判成
        # "内容已被项目改过"，升级路径就此失效（收官体检 A-06）
        if normalize(strip_node_regions(debranch(existing))) == normalize(strip_node_regions(template)):
            update.append((rel_dst, content))
            continue

        skip.append((rel_dst, "内容已被项目改过"))

    return deploy, update, skip


def deploy_enforcement(proj_root, upstream, merged_agents_text, dry_run, journal=None):
    """把执法包模板落到生效位置（gate.yml 的主干分支名跟随 §2，YAML-safe 渲染）。

    供单测直接调用的底层落盘助手；生产路径（install/sync）走 do_apply 的统一事务，
    每个写入都过 safe_project_path。返回 (新部署, 已更新, 跳过) 三个名字列表。
    """
    proj_root = Path(proj_root)
    deploy, update, skip = _enforce_actions(proj_root, upstream, merged_agents_text)
    if not dry_run:
        for rel_dst, content in deploy + update:
            dst, _ = safe_project_path(proj_root, rel_dst)
            original = read_text(dst) if dst.is_file() else None
            _ensure_parent(dst)
            write_text_atomic(dst, content)
            if journal is not None:
                journal.append((dst, original))
    return (
        [name for name, _ in deploy],
        [name for name, _ in update],
        skip,
    )


# --------------------------------------------------------------------------- #
# install / sync 统一事务：plan → backup（先落盘）→ write → move → commit
# --------------------------------------------------------------------------- #
BACKUP_DIRNAME = ".tsc-backup"
MANIFEST_NAME = "manifest.json"
MANIFEST_TMP = "manifest.json.new"   # committed 之前只以临时文件存在


def _manifest_payload(proj_root, writes, moves, contract_ver):
    """由事务 plan 生成可回滚清单（写入前状态 + 迁移记录）。"""
    proj_root = Path(proj_root)
    files = []
    for rel, _content, original in writes:
        files.append({
            "path": rel,
            "action": "modify" if original is not None else "create",
            "content": original,
        })
    move_entries = [{"from": src, "to": dst} for src, dst in moves]
    return {
        "schema": 2,
        "contract_version": contract_ver,
        "backed_up_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "files": files,
        "moves": move_entries,
    }


def _undo_transaction(applied_writes, applied_moves, created_dirs):
    """尽力恢复到事务开始前状态；单步失败只如实列出，不掩盖原始错误。"""
    problems = []
    for src, dst in reversed(applied_moves):
        try:
            shutil.move(str(dst), str(src))
        except OSError as exc:
            problems.append("迁移回滚失败 %s <- %s（%s）" % (src, dst, exc))
    for dst, original in reversed(applied_writes):
        try:
            if original is None:
                dst.unlink()
            else:
                write_text_atomic(dst, original)
        except OSError as exc:
            problems.append("写入回滚失败 %s（%s）" % (dst, exc))
    _remove_empty_dirs_quietly(created_dirs)
    return problems


def _execute_transaction(proj_root, plan, contract_ver):
    """执行完整事务。返回 (退出码, 回滚问题列表, 原始异常或 None)。

    顺序：备份清单先落盘为临时文件 → 逐项写入 → 旧结构迁移 → os.replace 提交
    （committed）。任一步失败：自动恢复到事务开始前状态、删除临时清单，绝不
    留半成品备份/迁移。previous manifest 在提交前始终原样保留。
    """
    proj_root = Path(proj_root)
    backup_dir = proj_root / AGENTS_DIR / BACKUP_DIRNAME
    tmp_manifest = backup_dir / MANIFEST_TMP
    manifest = _manifest_payload(proj_root, plan["writes"], plan["moves"], contract_ver)

    created_dirs = []
    applied_writes = []   # (绝对路径, 原内容或 None)
    applied_moves = []    # (源, 目标)
    try:
        # 1) 备份先落盘：项目文件被改动前，可回滚清单必须已经准备好
        created_dirs.extend(_ensure_parent(backup_dir))
        backup_dir_existed = backup_dir.exists()
        backup_dir.mkdir(parents=True, exist_ok=True)
        if not backup_dir_existed:
            created_dirs.append(backup_dir)  # 失败时连同空备份目录一并清掉
        write_text_atomic(tmp_manifest,
                          json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        # 2) 写入（全部过安全路径检查）
        for rel, content, original in plan["writes"]:
            dst, _ = safe_project_path(proj_root, rel)
            created_dirs.extend(_ensure_parent(dst))
            write_text_atomic(dst, content)
            applied_writes.append((dst, original))
        # 3) 旧结构迁移（与写入同一事务）
        for rel_src, rel_dst in plan["moves"]:
            src, _ = safe_project_path(proj_root, rel_src)
            dst, _ = safe_project_path(proj_root, rel_dst)
            created_dirs.extend(_ensure_parent(dst))
            shutil.move(str(src), str(dst))
            applied_moves.append((src, dst))
        # 4) 提交：临时清单替换正式清单，事务自此 committed
        os.replace(tmp_manifest, backup_dir / MANIFEST_NAME)
    except OSError as exc:
        # 先清掉本次事务的临时清单（半成品），再恢复项目原状——顺序不能反：
        # 留着临时清单会把（空的）备份目录占住，新建目录就清不干净了
        problems = []
        try:
            if tmp_manifest.exists():
                tmp_manifest.unlink()
        except OSError as exc2:
            problems.append("清理临时备份清单失败（%s）" % exc2)
        problems.extend(_undo_transaction(applied_writes, applied_moves, created_dirs))
        return EXIT_IO, problems, exc
    return EXIT_OK, [], None


def do_apply(proj_root, upstream, dry_run, force):
    """install / sync 共用的落地逻辑（统一事务）。返回退出码。

    所有权规则（绝不凭 §2 形状认定所有权）：
    - 无 AGENTS.md          → 全新接入；
    - 带 contract marker    → 托管，按 TSC 规则更新托管内容；
    - 旧版部署（无 marker 但凑齐 ≥2 个 TSC 历史特征）→ 一次性升级，重建时补 marker；
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
    example = upstream / TEMPLATE_PROJECT_EXAMPLE
    legacy_moves, legacy_leftover = plan_legacy_moves(proj_root)
    # commitlint 适配层判定必须在任何写盘前采样：部署后文件落地，再判定就会
    # 把 tsc 自己写的 commitlint.config.js 误认成"项目已有配置"（口径漂移）
    cl_wanted, cl_reason = commitlint_wanted(proj_root)

    # 2) 形成完整 mutation plan（零写盘）。写入项 = (相对路径, 新内容, 原内容/None)。
    writes = []
    if not project_agents.is_file() or read_text(project_agents) != merged:
        writes.append((AGENTS_MD, merged,
                       read_text(project_agents) if project_agents.is_file() else None))
    for rel, src in collect_payload(upstream):
        dst = proj_root / rel
        if dst.is_file() and read_text(dst) == read_text(src):
            continue
        writes.append((rel.as_posix(), read_text(src),
                       read_text(dst) if dst.is_file() else None))
    project_py_rel = (Path(AGENTS_DIR) / PROJECT_FILE).as_posix()
    if example.is_file() and not (proj_root / AGENTS_DIR / PROJECT_FILE).is_file():
        writes.append((project_py_rel, read_text(example), None))
    if not source_record_current(proj_root, upstream, up_ver):
        writes.append(
            ((Path(AGENTS_DIR) / SOURCE_FILE).as_posix(),
             json.dumps(_source_record_payload(upstream, up_ver), ensure_ascii=False, indent=2) + "\n",
             (read_text(proj_root / AGENTS_DIR / SOURCE_FILE)
              if (proj_root / AGENTS_DIR / SOURCE_FILE).is_file() else None)))
    deploy, update, enforce_skipped = _enforce_actions(proj_root, upstream, merged)
    for rel_dst, content in deploy + update:
        dst = proj_root / rel_dst
        writes.append((rel_dst, content, read_text(dst) if dst.is_file() else None))

    # 路径安全前置校验：plan 里任何一条路径越界/symlink 逃逸，整体拒绝
    try:
        for rel, _c, _o in writes:
            safe_project_path(proj_root, rel)
        for rel_src, rel_dst in legacy_moves:
            safe_project_path(proj_root, rel_src)
            safe_project_path(proj_root, rel_dst)
    except UnsafeProjectPath as exc:
        warn("拒绝执行：计划中的写入路径不安全（%s）。本次未写入任何文件。" % exc)
        return EXIT_STATE

    drift = [rel for rel, _c, _o in writes] + [rel_src for rel_src, _ in legacy_moves]
    if not force and not drift:
        say("已是最新：上游 v%s，逐项内容比对无漂移，无需变动。" % up_ver)
        for name, why in enforce_skipped:
            say("执法包跳过 %s（%s；项目已接管，技能不覆盖）。" % (name, why))
        if legacy_leftover:
            # 早退分支也不能吞掉迁移受阻信息（收官体检 A-10）
            say("检测到旧结构，但目标位置已有同名项，无法自动迁移（请人工确认）：%s"
                % "、".join(str(s.name) for s in legacy_leftover))
        return EXIT_OK
    if legacy_moves:
        say("检测到旧结构残留，继续执行迁移：%s" % "、".join(s for s, _ in legacy_moves))

    plan = {"writes": writes, "moves": legacy_moves}
    # 本次事务是否部署 project.py（事务后文件必已存在，事后判断恒假——A-08① 改采样）
    deploys_project_py = any(rel == project_py_rel for rel, _c, _o in writes)

    # 3) dry-run：只报告，零写盘（连备份临时文件都不产生）
    if dry_run:
        say("上游来源：%s（v%s）" % (upstream, up_ver))
        say("目标项目：%s" % proj_root)
        say("版本变化：%s → %s" % (local_ver or "（未接入）", up_ver))
        say("所有权：%s" % OWNERSHIP_LABEL[ownership])
        say("模式：--dry-run，未写入任何文件")
        for rel, _c, _o in writes:
            say("  将更新 %s" % rel)
        if legacy_moves:
            say("旧结构将迁移到 .agents/：")
            for src, dst in legacy_moves:
                say("  %s → %s" % (src, dst))
        for extra in legacy_leftover:
            say("旧位置已存在同名文件，未处理（请人工确认）：%s" % extra)
        for name in [n for n, _ in deploy]:
            say("执法包新部署（将写入）：%s" % name)
        for name in [n for n, _ in update]:
            say("执法包已随技能模板更新（将写入）：%s（带 tsc-managed 标记）" % name)
        for name, why in enforce_skipped:
            say("执法包跳过 %s（%s；技能不覆盖项目接管的文件。）" % (name, why))
        if deploys_project_py:
            say("下一步：编辑 .agents/project.py，填入本项目自己的门禁命令。")
        return EXIT_OK

    # 4) 真实事务：备份 → 写入 → 迁移 → 提交；任一步失败自动恢复原状
    code, problems, exc = _execute_transaction(proj_root, plan, up_ver)
    if code != EXIT_OK:
        warn("事务失败，已自动恢复到本次 install/sync 之前的状态（%s）。" % exc)
        for p in problems:
            warn("  回滚未彻底，请人工检查：%s" % p)
        warn("处理完上述问题后可重试；上一次成功事务的回滚清单未受影响。")
        return code

    # 5) 汇报
    say("上游来源：%s（v%s）" % (upstream, up_ver))
    say("目标项目：%s" % proj_root)
    say("版本变化：%s → %s" % (local_ver or "（未接入）", up_ver))
    say("所有权：%s" % OWNERSHIP_LABEL[ownership])
    for rel, _c, _o in writes:
        say("  已更新 %s" % rel)
    if legacy_moves:
        say("旧结构已迁移到 .agents/：")
        for src, dst in legacy_moves:
            say("  %s → %s" % (src, dst))
    for extra in legacy_leftover:
        say("旧位置已存在同名文件，未处理（请人工确认）：%s" % extra)

    deployed = [n for n, _ in deploy]
    enforced_updated = [n for n, _ in update]
    if deployed:
        say("执法包新部署（已写入）：")
        for name in deployed:
            say("  %s" % name)
    if enforced_updated:
        say("执法包已随技能模板更新（已写入）：")
        for name in enforced_updated:
            say("  %s（带 tsc-managed 标记，视为技能托管）" % name)
    for name, why in enforce_skipped:
        say("执法包跳过 %s（%s；技能不覆盖项目接管的文件。如需对齐最新模板，"
            "请先自行备份再删掉该项目文件重跑 install）。" % (name, why))

    if is_node_project(proj_root):
        if cl_wanted:
            say("Node 项目：commitlint 已随执法包部署。")
            say("  启用本地钩子前先装依赖：npm i -D @commitlint/cli @commitlint/config-conventional")
        else:
            say("Node 项目，%s：不部署 TSC 的 commitlint 适配层（尊重项目现状）。" % cl_reason)
        pm = detect_lockfile_pm(proj_root)
        if pm:
            say("提示：检测到 %s 锁文件。pre-commit 的 commitlint entry 默认走 npx/npm，"
                "请按项目实际包管理器调整。" % pm)
    else:
        say("未检测到 package.json：按非 Node 项目处理，不部署 commitlint、不引入任何 npm 依赖。")
    say("本地钩子激活（可选，不想被拦就别执行）：pip install pre-commit && "
        "pre-commit install && pre-commit install --hook-type commit-msg")
    say("密钥扫描 / commitlint 的全量兜底在 CI（.github/workflows/gate.yml），无需本地依赖。")
    if any(rel in ((Path(AGENTS_DIR) / VERSION_FILE).as_posix(),
                   (Path(AGENTS_DIR) / SOURCE_FILE).as_posix())
           for rel, _c, _o in writes):
        # A-11：这两个部署生成物（.source 含本机路径）不提示 ignore，每个接入项目
        # 都会常驻 2 个未跟踪文件
        say("提示：.agents/VERSION 与 .agents/.source 是部署生成物（.source 含本机路径），"
            "建议加入项目 .gitignore（或有意随仓库入库，二选一）。")
    if deploys_project_py:
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
# project.py：AST 安全解析（白名单常量；绝不 exec）
# --------------------------------------------------------------------------- #
def _ast_const_value(node, where):
    """AST 表达式 -> Python 常量；一切可执行结构（调用/属性/名字/…）都拒绝。"""
    if isinstance(node, ast.Constant):
        value = node.value
        if value is None or isinstance(value, (str, int, float, bool)):
            return value, None
        return None, "%s：不支持的常量类型 %s" % (where, type(value).__name__)
    if isinstance(node, ast.Dict):
        out = {}
        for key, val in zip(node.keys, node.values):
            if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                return None, "%s：字典键必须是字符串字面量" % where
            item, err = _ast_const_value(val, where)
            if err:
                return None, err
            out[key.value] = item
        return out, None
    if isinstance(node, (ast.List, ast.Tuple)):
        out = []
        for element in node.elts:
            item, err = _ast_const_value(element, where)
            if err:
                return None, err
            out.append(item)
        return out, None
    if isinstance(node, ast.Call):
        return None, "%s：禁止函数调用" % where
    if isinstance(node, ast.Attribute):
        return None, "%s：禁止属性访问" % where
    if isinstance(node, ast.Name):
        return None, "%s：禁止变量引用（只允许字面量）" % where
    return None, "%s：禁止表达式 %s" % (where, type(node).__name__)


def parse_project_config(path):
    """AST 解析 project.py，只取白名单配置。返回 (配置 dict 或 None, 错误信息)。

    允许：模块 docstring、简单赋值（值只能是 None / 字符串 / 数字 / 布尔 /
    字符串键字典 / 常量列表）。白名单外的常量赋值（如 __all__）允许但忽略。
    禁止：import、函数调用、属性访问、变量引用、任意其他语句——配置文件绝不
    被执行，夹带的代码一行也不会跑（doctor / check-config / verify / CI 同源）。
    """
    path = Path(path)
    try:
        tree = ast.parse(read_text(path), filename=str(path))
    except (SyntaxError, ValueError) as exc:
        return None, "%s 语法无法解析：%s" % (path, exc)
    cfg = {}
    for node in tree.body:
        where = "%s 第 %d 行" % (path.name, getattr(node, "lineno", 0))
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue  # 模块 docstring
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            return None, "%s：project.py 禁止 import（配置只允许白名单常量，绝不执行）" % where
        if isinstance(node, ast.Assign):
            value, err = _ast_const_value(node.value, where)
            if err:
                return None, err
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in CONFIG_KEYS:
                    cfg[target.id] = value
            continue
        return None, "%s：不允许的语句 %s（只允许简单赋值）" % (where, type(node).__name__)
    timeouts = cfg.get(GATE_TIMEOUTS_KEY)
    if timeouts is not None and not isinstance(timeouts, dict):
        return None, "%s 必须是字典（如 {\"TEST_CMD\": 300}）" % GATE_TIMEOUTS_KEY
    return cfg, None


def load_project_config(proj_root):
    """兼容旧调用名的薄封装：AST 安全解析 project.py。"""
    cfg_path = Path(proj_root) / AGENTS_DIR / PROJECT_FILE
    if not cfg_path.is_file():
        warn("找不到 %s，请先执行 install 或手工创建。" % cfg_path)
        return None
    cfg, err = parse_project_config(cfg_path)
    if cfg is None:
        warn("%s 无法加载（AST 白名单解析）：%s" % (cfg_path, err))
    return cfg


# --------------------------------------------------------------------------- #
# 聚合门禁（每条命令都有超时；超时杀整个进程组，绝不无限等待）
# --------------------------------------------------------------------------- #
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


# 门禁命令的首令牌可能是 python / python3 / py。命令源（AGENTS.md §2 与
# .agents/project.py）必须是两处一致的静态字符串，写不出 sys.executable；而解释器
# 名字各平台不齐——Windows 常见只有 python，部分 Linux/macOS 只有 python3。写死
# 任何一个都会在另一平台上变成"命令找不到"，于是门禁在最需要它的时候崩掉。
# 这里做一次回退：PATH 里解析得到就不动，解析不到才换成当前解释器（并明确告警）。
_INTERPRETER_HEAD = re.compile(
    r'^(?P<indent>\s*)(?P<quote>"?)(?P<token>(?:py|python[0-9.]*)(?:\.exe)?)(?P=quote)(?=\s|$)',
    re.IGNORECASE,
)


def retarget_interpreter(command):
    """首令牌是解释器且 PATH 里解析不到时，换成当前解释器。返回 (命令, 是否改过)。"""
    if not command:
        return command, False
    m = _INTERPRETER_HEAD.match(command)
    if m is None or shutil.which(m.group("token")):
        return command, False
    return '%s"%s"%s' % (m.group("indent"), sys.executable, command[m.end():]), True


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
    command, retargeted = retarget_interpreter(command)
    if retargeted:
        warn("该命令写的解释器在 PATH 里找不到，已改用当前解释器执行：%s" % command)
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
        if not isinstance(command, str):
            # AST 白名单允许 list/int 等常量；不设防会在正则匹配处裸崩（最终审查 F-01）
            warn("%s 的值必须是字符串或 None，当前是 %s——请修正 .agents/project.py。"
                 % (key, type(command).__name__))
            warn("门禁结论：配置非法（退出码 %d）" % EXIT_STATE)
            return EXIT_STATE
        raw_timeout = timeout_override or per_step.get(key) or DEFAULT_TIMEOUT_S
        try:
            timeout_s = max(1, int(raw_timeout))
        except (TypeError, ValueError):
            warn('%s["%s"] 的超时值 %r 无法解释为秒数——请修正 .agents/project.py。'
                 % (GATE_TIMEOUTS_KEY, key, raw_timeout))
            warn("门禁结论：配置非法（退出码 %d）" % EXIT_STATE)
            return EXIT_STATE
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
    "Format": "FMT_CHECK_CMD",
    "format": "FMT_CHECK_CMD",
    "静态检查": "LINT_CMD",
    "Lint": "LINT_CMD",
    "lint": "LINT_CMD",
    "测试": "TEST_CMD",
    "Test": "TEST_CMD",
    "test": "TEST_CMD",
    "构建": "BUILD_CMD",
    "Build": "BUILD_CMD",
    "build": "BUILD_CMD",
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

    if any(PLACEHOLDER in (v or "") for v in table.values()):
        # §2 尚未适配：与 CI 内联壳同口径从严（check-config 绿必须意味着真同源，
        # "跳过校验给 rc=0"是假绿——收官体检 A-04②）
        warn("§2 仍是 %s 占位（项目未适配）：同源校验不通过。" % PLACEHOLDER)
        warn("先按 BOOTSTRAP 探测填充 §2 与 .agents/project.py，再重跑本命令。")
        return EXIT_MERGE

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
# update：只更新技能本体（与项目 sync 严格分开）
# --------------------------------------------------------------------------- #
def _repo_tracks_skill(host_repo, skill_root):
    """host_repo 这个 git 仓库是否真的收录了 skill_root（防止误 pull 宿主项目自己的仓库）。

    `git_worktree_of` 只是逐级向上找第一个含 .git 的祖先——技能被装进
    `<宿主项目>/.claude/skills/tsc` 这类位置时，找到的是**宿主项目自己的仓库**；
    不加校验就 pull，等于替宿主项目执行了 git pull 还谎报"本体已是最新"
    （收官体检 A-09）。判据：git ls-files 能在索引里找到本技能的 VERSION。
    """
    try:
        rel = Path(skill_root).resolve().relative_to(Path(host_repo).resolve())
    except ValueError:
        return False
    try:
        proc = subprocess.run(
            ["git", "-C", str(host_repo), "ls-files", "--error-unmatch",
             rel.joinpath(VERSION_FILE).as_posix()],
            capture_output=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def cmd_update(timeout_s):
    root = upstream_root()
    old_ver = upstream_version(root) or "未知"
    host_repo = git_worktree_of(root)
    if host_repo is None or not _repo_tracks_skill(host_repo, root):
        warn("技能目录不在任何收录它的 git 仓库里（未找到 .git，或所在仓库没有跟踪本技能）——")
        warn("通常是宿主插件市场 / 压缩包 / 项目内嵌安装，本脚本无从拉取，也绝不 pull 宿主项目自己的仓库。")
        warn("本体更新请走宿主机制：打开宿主平台的插件/技能管理页，更新 tsc；")
        warn("或用 git clone / 市场重装修复后重试。项目契约不受影响，仍可 sync/verify。")
        return EXIT_STATE
    say("本体目录：%s（当前 v%s）" % (root, old_ver))
    say("$ git -C %s pull --ff-only（超时 %ss）" % (host_repo, timeout_s))
    try:
        proc = subprocess.run(
            ["git", "-C", str(host_repo), "pull", "--ff-only"],
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
        return EXIT_MERGE  # 归一为契约退出码 1（需人工处理），不透传 git 原始码（A-08②）
    new_ver = upstream_version(root) or "未知"
    if new_ver == old_ver:
        say("本体已是最新：v%s（无版本变化）。" % old_ver)
    else:
        say("本体已更新：v%s → v%s。" % (old_ver, new_ver))
        say("提示：技能/钩子在本会话中可能仍是旧载入；新开会话后生效。")
        say("如需把当前项目契约同步到新版本，接着执行：tsc sync --project <项目根>")
    return EXIT_OK


# --------------------------------------------------------------------------- #
# rollback：恢复上一次成功 install/sync 写盘之前的项目契约状态
# --------------------------------------------------------------------------- #
def _validated_manifest_actions(proj_root, manifest):
    """先完整校验 manifest，再生成回滚动作清单。返回 (动作列表, 问题列表)。

    动作生成的顺序与写入相反（先搬回迁移、再逆序还原/删除文件）。
    任何一条路径非法（绝对路径 / `..` / 越出项目根 / symlink 组件 / 字段缺失），
    整个回滚拒绝执行——绝不"恢复一半"。
    """
    proj_root = Path(proj_root)
    problems, actions = [], []
    files = manifest.get("files", [])
    moves = manifest.get("moves", [])
    if not isinstance(files, list) or not isinstance(moves, list):
        return [], ["回滚清单结构非法（files/moves 不是列表）"]
    for entry in moves:
        if not isinstance(entry, dict):
            problems.append("moves 含非对象条目：%r" % (entry,))
            continue
        src_rel, dst_rel = entry.get("from"), entry.get("to")
        if not isinstance(src_rel, str) or not isinstance(dst_rel, str):
            problems.append("moves 条目缺 from/to：%r" % (entry,))
            continue
        try:
            src, _ = safe_project_path(proj_root, src_rel)
            dst, _ = safe_project_path(proj_root, dst_rel)
        except UnsafeProjectPath as exc:
            problems.append("moves 路径非法（%s）：%r" % (exc, entry))
            continue
        actions.append(("move_back", src, dst))
    for entry in reversed(files):
        if not isinstance(entry, dict):
            problems.append("files 含非对象条目：%r" % (entry,))
            continue
        rel = entry.get("path")
        action = entry.get("action")
        if not isinstance(rel, str) or action not in ("create", "modify"):
            problems.append("files 条目非法：%r" % (entry,))
            continue
        if action == "modify" and not isinstance(entry.get("content"), str):
            problems.append("modify 条目缺 content：%r" % (entry,))
            continue
        try:
            target, _ = safe_project_path(proj_root, rel)
        except UnsafeProjectPath as exc:
            problems.append("files 路径非法（%s）：%r" % (exc, entry))
            continue
        actions.append(("restore", target, entry))
    return actions, problems


def cmd_rollback(proj_root):
    proj_root = Path(proj_root)
    manifest_path = proj_root / AGENTS_DIR / BACKUP_DIRNAME / MANIFEST_NAME
    if not manifest_path.is_file():
        warn("没有可回滚的记录（%s 不存在）。" % manifest_path)
        warn("rollback 只能撤销最近一次 install/sync 的写入。")
        return EXIT_STATE
    try:
        manifest = json.loads(read_text(manifest_path))
    except (ValueError, OSError) as exc:
        warn("回滚清单损坏，拒绝盲目恢复：%s" % exc)
        return EXIT_IO
    if not isinstance(manifest, dict):
        warn("回滚清单结构非法（不是 JSON 对象），拒绝恢复。")
        return EXIT_IO

    # 第一次写入之前：完整校验整个 manifest
    actions, problems = _validated_manifest_actions(proj_root, manifest)
    if problems:
        warn("回滚清单未通过完整校验，拒绝恢复（避免恢复一半）：")
        for p in problems:
            warn("  - %s" % p)
        return EXIT_IO

    restored = []
    for kind, a, b in actions:
        try:
            if kind == "move_back":
                # b(.agents/x) 搬回 a(根/x)；根位置若又被占用，如实报告不硬拆
                if a.exists():
                    problems.append("原位置已被占用，未搬回：%s" % a)
                    continue
                _ensure_parent(a)
                shutil.move(str(b), str(a))
                restored.append(("moved", a))
            else:  # restore
                entry = b
                if entry["action"] == "create":
                    if a.is_file():
                        a.unlink()
                else:
                    _ensure_parent(a)
                    write_text_atomic(a, entry["content"])
                restored.append((entry["action"], a))
        except OSError as exc:
            problems.append("%s（%s）" % (a, exc))
    if problems:
        # 回滚未彻底：清单必须保留，否则用户连重试的机会都没有（收官体检 A-02）
        for p in problems:
            warn("  回滚未彻底，请人工检查：%s" % p)
        warn("备份清单已保留（%s），处理完上述问题后可重试 rollback。" % manifest_path)
        for action, target in restored:
            say("  本次已%s %s" % ("删除（上次新建）" if action == "create" else
                                  "搬回" if action == "moved" else "还原", target))
        return EXIT_IO
    try:
        shutil.rmtree(manifest_path.parent)
    except OSError as exc:
        warn("清理备份目录失败（%s）——回滚本身已完成，只是清单残留。" % exc)
        return EXIT_IO
    say("已回滚到 %s 之前的状态（契约版本 %s）。" % (
        manifest.get("backed_up_at", "上次同步"), manifest.get("contract_version", "未知")))
    for action, target in restored:
        if action == "create":
            say("  已删除（上次新建）%s" % target)
        elif action == "moved":
            say("  已搬回 %s" % target)
        else:
            say("  已还原 %s" % target)
    say("注意：回滚只撤销最近一次成功的 install/sync；之后项目里的手工修改会被还原内容覆盖。")
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
        # 目标是否已被占用决定措辞：占位冲突时 sync 搬不动，不能承诺"会自动搬"（A-10）
        _moves, legacy_blocked = plan_legacy_moves(proj_root)
        if legacy_blocked:
            line("检测到旧结构（目标位置已有同名项，sync 无法自动迁移，需人工确认）",
                 "、".join(str(s.name) for s in legacy_blocked))
        else:
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
        add("上游来源", "fail", "无法定位（本脚本应位于 <技能根>/scripts/ 下）")
    else:
        missing = validate_upstream(upstream)
        up_ver = upstream_version(upstream)
        if missing:
            add("上游来源", "fail", "%s 不完整：%s" % (upstream, "；".join(missing)))
        else:
            add("上游来源", "ok", "%s（v%s）" % (upstream, up_ver))
    host_repo = git_worktree_of(upstream_root())
    if host_repo is not None:
        add("本体更新通道", "ok", "git 安装（%s；tsc update 可直接 pull）" % host_repo)
    else:
        add("本体更新通道", "warn", "非 git 安装：本体更新走宿主插件/技能管理（tsc update 不适用）")

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
    else:
        cfg, err = parse_project_config(project_py)
        if cfg is None:
            add("门禁命令源", "fail", "project.py 无法通过 AST 白名单解析：%s" % err)
        elif section2_filled:
            comparable, mismatch = _config_mismatches(proj_root, cfg)
            if not comparable:
                add("§2 ⇆ project.py", "fail", "；".join(mismatch))
            elif mismatch:
                add("§2 ⇆ project.py", "fail", "不一致：%s" % "、".join(mismatch))
            else:
                add("§2 ⇆ project.py", "ok", "同源一致")

    node = is_node_project(proj_root)
    if node:
        wanted, reason = commitlint_wanted(proj_root)
        if wanted:
            npm = shutil.which("npm")
            add("项目类型", "ok" if npm else "warn",
                "Node/JS（package.json）；commitlint 适配层已部署"
                + ("" if npm else "，但 npm 不在 PATH（commitlint 钩子无法本地运行，CI 兜底）"))
        else:
            add("项目类型", "ok", "Node/JS，%s：不部署 TSC commitlint 适配层" % reason)
        pm = detect_lockfile_pm(proj_root)
        if pm:
            add("包管理器", "warn",
                "检测到 %s 锁文件：pre-commit 的 commitlint entry 默认走 npx/npm，请按项目包管理器调整" % pm)
    else:
        add("项目类型", "ok", "非 Node 项目：不部署 commitlint，零 npm 依赖")

    if is_self_bootstrap(proj_root, upstream):
        add("执法包", "ok", "上游本体自身：按设计不铺生效件（模板原件在技能 templates/ 下）")
    else:
        enforce_state = []
        for rel_src, rel_dst in ENFORCE_DEPLOY.items():
            if rel_src in NODE_ONLY_ENFORCE and not commitlint_wanted(proj_root)[0]:
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


def _config_mismatches(proj_root, cfg=None):
    """§2 与 project.py 同源校验（供 doctor 用）。返回 (是否可比较, mismatch 列表)。"""
    if cfg is None:
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
    parser.add_argument("--source", dest="source", default=None, help="显式上游（本地技能目录）")
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
    except UnsafeProjectPath as exc:
        warn("拒绝执行：路径不安全（%s）。" % exc)
        return EXIT_STATE
    except OSError as exc:
        # 顶层兜底：读盘 / 定位上游等未捕获的 IO 异常按契约归一为退出码 2
        warn("执行失败（IO / 权限 / 文件占用）：%s" % exc)
        return EXIT_IO


def _dispatch(args):
    if args.dry_run and args.command in ("rollback", "update"):
        # rollback 会真实改/删文件、update 会真实 git pull——静默忽略 --dry-run
        # 曾让"预览"变"执行"（收官体检 A-03），这里显式拒绝而不是悄悄跑
        warn("%s 不支持 --dry-run（%s）。要看当前状态请用 status / doctor。"
             % (args.command,
                "rollback 会真实还原/删除文件" if args.command == "rollback"
                else "update 会真实执行 git pull"))
        return EXIT_STATE

    if args.project:
        proj_root = Path(normalize_path_arg(args.project)).expanduser().resolve()
    else:
        proj_root = Path.cwd()

    if args.command == "update":
        return cmd_update(args.timeout if args.timeout else DEFAULT_TIMEOUT_S)

    if not proj_root.is_dir():
        warn("目标项目目录不存在：%s" % proj_root)
        return EXIT_STATE

    if args.command == "rollback":
        return cmd_rollback(proj_root)

    upstream = None
    if args.command in ("status", "install", "sync", "doctor"):
        upstream = find_upstream(args.source)
        missing = validate_upstream(upstream)
        if missing:
            warn("上游不完整（必需产物缺失或格式非法），拒绝 install/sync：")
            for item in missing:
                warn("  - %s" % item)
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
