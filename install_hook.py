#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""install_hook.py - 给某个 git 仓库装上结构门禁（pre-commit 钩子）

作用：提交前自动对暂存的代码文件跑 structure_guard（五层：编码/括号平衡/
      权威语法/调用形态/项目断言），结构有问题就阻止提交——
      坏代码进不了仓库，而不是等 CI 或运行时才发现。

安全约束（刻意收窄）：
  - 只写目标仓库的 .git/hooks/pre-commit，不碰任何源码文件
  - 已存在同名钩子默认拒绝覆盖，除非显式 --force（覆盖前自动备份为 pre-commit.bak）
  - 不修改 git 全局配置，不写 ~/.gitconfig

退出码语义（与 structure_guard 契约一致）：
  退出码 1 = 代码结构问题 → 拦截提交
  退出码 2/3 = 门禁自身故障 → 告警放行（不冒充代码问题），CI 层兜底

用法：
    python install_hook.py --repo /path/to/repo
    python install_hook.py --repo . --force      # 覆盖已有钩子（会先备份）
    python install_hook.py --repo . --uninstall  # 卸载
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import sys

HOOK_NAME = "pre-commit"
MARKER = "# >>> bracket-balance-guard >>>"
END_MARKER = "# <<< bracket-balance-guard <<<"

HOOK_BODY = """{marker}
# 提交前检查暂存文件的结构完整性（括号平衡/语法/缩进/形态）。由 bracket-balance-guard 技能安装。
# 卸载：删除本标记块，或运行 install_hook.py --uninstall
_bg_files=$(git diff --cached --name-only --diff-filter=ACM)
if [ -n "$_bg_files" ]; then
  {python} {script} --quiet --staged --color never
  _bg_rc=$?
  if [ "$_bg_rc" -eq 1 ]; then
    echo ""
    echo "  >> 结构门禁未通过，已阻止本次提交。按上面给的行列修好，再 git add。"
    echo "  >> 确认要跳过：git commit --no-verify"
    exit 1
  elif [ "$_bg_rc" -ne 0 ]; then
    echo ""
    echo "  >> 结构门禁自身异常(退出码 $_bg_rc)，本次不拦截，请尽快排查（CI 会兜底）。"
  fi
fi
{end_marker}
"""


def find_git_dir(repo: str) -> str | None:
    d = os.path.abspath(repo)
    # 目录不存在时直接失败：否则 os.path.dirname 会一路上溯，
    # 可能把钩子装到某个毫不相干的上级仓库里。
    if not os.path.isdir(d):
        return None
    while True:
        cand = os.path.join(d, ".git")
        if os.path.isdir(cand):
            return cand
        if os.path.isfile(cand):  # worktree / submodule：.git 是文件
            return None
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def build_block() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    script = os.path.join(here, "structure_guard.py")
    script = script.replace("\\", "/")
    prev = os.path.join(here, "precommit_prev.tmp").replace("\\", "/")
    py = sys.executable.replace("\\", "/")
    return HOOK_BODY.format(marker=MARKER, end_marker=END_MARKER, python=py, script=script)


def strip_existing(text: str) -> str:
    """移除本技能以前写入的标记块（保留用户自己的内容）"""
    out, skip = [], False
    for line in text.splitlines(keepends=True):
        if MARKER in line:
            skip = True
            continue
        if END_MARKER in line:
            skip = False
            continue
        if not skip:
            out.append(line)
    return "".join(out)


def make_executable(path: str) -> None:
    mode = os.stat(path).st_mode
    os.chmod(path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="给 git 仓库安装结构检查 pre-commit 钩子")
    ap.add_argument("--repo", default=".", help="仓库路径（默认当前目录）")
    ap.add_argument("--force", action="store_true", help="覆盖已有 pre-commit 钩子（先备份）")
    ap.add_argument("--uninstall", action="store_true", help="卸载本技能写入的钩子")
    args = ap.parse_args(argv)

    git_dir = find_git_dir(args.repo)
    if not git_dir:
        print(f"找不到 git 仓库：{os.path.abspath(args.repo)}", file=sys.stderr)
        return 2

    hooks_dir = os.path.join(git_dir, "hooks")
    os.makedirs(hooks_dir, exist_ok=True)
    hook_path = os.path.join(hooks_dir, HOOK_NAME)
    existing = ""
    if os.path.exists(hook_path):
        with open(hook_path, "r", encoding="utf-8", errors="replace") as fh:
            existing = fh.read()

    if args.uninstall:
        if MARKER not in existing:
            print("该仓库的 pre-commit 钩子不是本技能装的，未做改动。")
            return 0
        rest = strip_existing(existing).strip()
        # 剥掉标记块后只剩 shebang（或什么都不剩），说明这个钩子本来就是本工具
        # 从零创建的，直接删掉；否则说明用户自己有内容，只移除标记块。
        if rest and rest != "#!/bin/sh":
            with open(hook_path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(rest + "\n")
            make_executable(hook_path)
            print(f"已移除括号检查块，保留了你原有的钩子内容：{hook_path}")
        else:
            os.remove(hook_path)
            print(f"已彻底卸载钩子：{hook_path}")
        return 0

    if existing and MARKER not in existing and not args.force:
        print(
            f"该仓库已有自己的 pre-commit 钩子，未做改动：{hook_path}\n"
            f"想保留它并追加括号检查：先用 --force（会自动备份为 pre-commit.bak），"
            f"再把原来的内容合并回去。",
            file=sys.stderr,
        )
        return 2

    if existing and MARKER not in existing and args.force:
        bak = hook_path + ".bak"
        shutil.copyfile(hook_path, bak)
        print(f"已备份原钩子 -> {bak}")

    base = strip_existing(existing)
    block = build_block()

    # 若原钩子已有 shebang，就追加标记块；否则新建完整脚本
    if base.strip().startswith("#!"):
        new_text = base.rstrip("\n") + "\n\n" + block
    else:
        new_text = "#!/bin/sh\n\n" + base + block

    with open(hook_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(new_text)
    make_executable(hook_path)

    print(f"已安装结构门禁：{hook_path}")
    print("  仓库根：" + os.path.dirname(git_dir))
    print("  解释器：" + sys.executable)
    print("  检查器：" + os.path.join(os.path.dirname(os.path.abspath(__file__)), "structure_guard.py"))
    print("  跳过一次提交：git commit --no-verify")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())
