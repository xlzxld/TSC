# -*- coding: utf-8 -*-
"""structure_guard 单元测试 —— 门禁自身的回归防线（检查器坏了比没有更危险）。

覆盖：check_source 分层判定（L1/L2/L3/跳过）、退出码优先级、CLI 行为、
闸1 hook 模式（拦截/放行/fail-open）、目录扫描过滤、钩子安装器指向。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(ROOT, "skills", "tsc", "scripts")
for p in (SCRIPTS,):
    if p not in sys.path:
        sys.path.insert(0, p)

import structure_guard as sg  # noqa: E402


def src_of(rel):
    with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as fh:
        return fh.read()


class CheckSourceTests(unittest.TestCase):
    def check(self, label, src):
        return sg.check_source(label, src, real_file=False)

    def test_py_ok(self):
        r = self.check("a.py", "x = 1\n")
        self.assertTrue(r["ok"])
        self.assertIsNone(r["tool_error"])

    def test_py_unbalanced_reported_by_L1(self):
        r = self.check("a.py", "x = (1\n")
        self.assertFalse(r["ok"])
        self.assertTrue(any(i["layer"] == "L1" and i["code"] == "unclosed"
                            for i in r["issues"]))
        self.assertEqual(r["suggestion"], ")")

    def test_py_syntax_error_reported_by_L2(self):
        r = self.check("a.py", "def f(:\n    pass\n")
        self.assertFalse(r["ok"])
        self.assertTrue(any(i["layer"] == "L2" for i in r["issues"]))

    def test_py_indent_error(self):
        r = self.check("a.py", "x = 1\n  y = 2\n")
        self.assertFalse(r["ok"])
        self.assertTrue(any(i["layer"] == "L2" for i in r["issues"]))

    def test_py_tab_space_mix(self):
        r = self.check("a.py", "def f():\n\treturn 1\n    x = 2\n")
        self.assertFalse(r["ok"])

    def test_py_fullwidth_in_string_is_legal(self):
        self.assertTrue(self.check("a.py", 's = "（中文）"\n')["ok"])

    def test_json_ok_and_broken(self):
        self.assertTrue(self.check("a.json", '{"a": [1]}')["ok"])
        r = self.check("a.json", '{"a": [1}')
        self.assertFalse(r["ok"])
        self.assertGreaterEqual(r["issues"][0]["line"], 1)

    def test_lisp_setq_odd_args(self):
        r = self.check("a.lsp", "(defun f (x)\n  (setq y x 2)\n  (list y))\n")
        self.assertFalse(r["ok"])
        self.assertTrue(any(i["code"] == "setq-odd-args" for i in r["issues"]))

    def test_lisp_if_arity(self):
        r = self.check("a.lsp", "(defun f (x)\n  (if x 1 2 3))\n")
        self.assertFalse(r["ok"])
        self.assertTrue(any(i["code"] == "if-arity" for i in r["issues"]))

    def test_lisp_foreach_min_args(self):
        r = self.check("a.lsp", "(defun f (l)\n  (foreach e l))\n")
        self.assertFalse(r["ok"])
        self.assertTrue(any(i["code"] == "foreach-arity" for i in r["issues"]))

    def test_lisp_nested_defun(self):
        r = self.check("a.lsp",
                       "(defun outer (x)\n  (defun inner (y) y)\n  (inner x))\n")
        self.assertFalse(r["ok"])
        self.assertTrue(any(i["code"] == "nested-defun" for i in r["issues"]))

    def test_lisp_quoted_list_no_false_positive(self):
        # 坑 #75 回归口径：引用糖粘合后 setq 仍为偶数参数
        self.assertTrue(self.check(
            "a.lsp",
            "(defun f ()\n  (setq pts '((1 2) (3 4)))\n  (length pts))\n")["ok"])

    def test_lisp_brackets_inside_string_are_legal(self):
        self.assertTrue(self.check("a.lsp", '(princ "(hello)")\n')["ok"])

    def test_md_skipped(self):
        r = self.check("a.md", "# 标题（全角括号合法）\n")
        self.assertEqual(r["skipped"], "docs")


class ExitCodeTests(unittest.TestCase):
    def test_issue_beats_tool_error(self):
        self.assertEqual(sg.exit_code_for(
            [{"issues": [1], "tool_error": "boom"}]), 1)

    def test_tool_error_alone(self):
        self.assertEqual(sg.exit_code_for(
            [{"issues": [], "tool_error": "boom"}]), 2)

    def test_clean(self):
        self.assertEqual(sg.exit_code_for(
            [{"issues": [], "tool_error": None}]), 0)


class CliTests(unittest.TestCase):
    def test_selftest_green(self):
        self.assertEqual(sg.main(["--selftest"]), 0)

    def test_unknown_lang_is_config_error(self):
        self.assertEqual(sg.main(["--lang", "nope", "whatever.py"]), 3)

    def test_real_bad_file_exit_1(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "bad.py")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("x = (1\n")
            self.assertEqual(sg.main([p, "--color", "never"]), 1)

    def test_real_good_file_exit_0(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "ok.py")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("x = 1\n")
            self.assertEqual(sg.main([p, "--color", "never", "--quiet"]), 0)

    def test_guard_scripts_themselves_are_clean(self):
        for rel in ("skills/tsc/scripts/bracket_lint.py", "skills/tsc/scripts/install_hook.py",
                    "skills/tsc/scripts/structure_guard.py"):
            self.assertEqual(sg.main([os.path.join(ROOT, rel), "--quiet",
                                      "--color", "never"]), 0, rel)

    def test_stdin_broken_bracket_exits_1(self):
        # B-01：stdin 管道输入不平衡代码必须真实拦截（退出码 1），不能因二次读空而假绿
        rc = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "structure_guard.py"), "--lang", "py", "-"],
            input="def foo(\n", capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(rc.returncode, 1)
        self.assertIn("unclosed", rc.stdout)

    def test_stdin_syntax_error_exits_1(self):
        # B-01/B-05：stdin 管道输入括号平衡但语法错误时，L2 正确分派并拦截（退出码 1）
        rc = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "structure_guard.py"), "--lang", "py", "-"],
            input="x = 1 + * 2\n", capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(rc.returncode, 1)
        self.assertIn("syntax-error", rc.stdout)

    def test_extensionless_script_runs_l2_syntax_check(self):
        # B-05：无扩展名脚本根据 shebang 触发 L2 语法检查，不能静默放行
        res = sg.check_source("my_cli", "#!/usr/bin/env python3\nx = 1 + * 2\n", real_file=False)
        self.assertFalse(res["ok"])
        self.assertTrue(any(i["layer"] == "L2" and i["code"] == "syntax-error" for i in res["issues"]))


    def _run_hook(self, stdin_text):
        return subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "structure_guard.py"), "--from-hook"],
            input=stdin_text, capture_output=True, text=True,
            encoding="utf-8", errors="replace")

    def test_hook_blocks_broken_file_with_exit_2(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "bad.py")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("x = (1\n")
            rc = self._run_hook(json.dumps({"tool_input": {"file_path": p}}))
            self.assertEqual(rc.returncode, 2)
            self.assertIn("unclosed", rc.stderr)

    def test_hook_passes_clean_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "ok.py")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("x = 1\n")
            rc = self._run_hook(json.dumps({"tool_input": {"file_path": p}}))
            self.assertEqual(rc.returncode, 0)

    def test_hook_fails_open_on_garbage_stdin(self):
        rc = self._run_hook("not json")
        self.assertEqual(rc.returncode, 0)

    def test_hook_fails_open_on_empty_payload(self):
        rc = self._run_hook("{}")
        self.assertEqual(rc.returncode, 0)


class ExpandPathsTests(unittest.TestCase):
    def test_dir_walk_filters_ext_and_skips_dirs(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, ".git"))
            os.makedirs(os.path.join(d, "sub"))
            for rel, text in (("a.py", "x = 1\n"), ("b.md", "# t\n"),
                              ("sub/c.lsp", "(princ 1)\n"), (".git/x.py", "y = 2\n")):
                with open(os.path.join(d, rel), "w", encoding="utf-8") as fh:
                    fh.write(text)
            files, truncated = sg.expand_paths([d])
            names = sorted(os.path.relpath(f, d).replace("\\", "/") for f in files)
            self.assertEqual(names, ["a.py", "sub/c.lsp"])
            self.assertEqual(truncated, 0)


class InstallHookContractTests(unittest.TestCase):
    def test_hook_targets_guard_with_staged_mode(self):
        text = src_of("skills/tsc/scripts/install_hook.py")
        self.assertIn("structure_guard.py", text)
        self.assertIn("--staged", text)

    def test_hook_blocks_only_on_exit_1(self):
        text = src_of("skills/tsc/scripts/install_hook.py")
        self.assertIn('-eq 1', text)
        self.assertIn("本次不拦截", text)

    def test_hook_prefers_portable_project_copy(self):
        # 闸2 可移植性：钩子优先调项目内落盘件（相对路径），仓库换机器仍有效
        import install_hook as ih
        block = ih.build_block()
        self.assertIn('.agents/structure_guard.py', block)
        self.assertIn("tsc-structure-guard", ih.MARKER)

    def test_generated_hook_block_is_valid_shell_text(self):
        # 标记块可被 strip_existing 完整剥除（幂等装卸的基础）
        import install_hook as ih
        base = "#!/bin/sh\n\necho user-own\n"
        combined = base + ih.build_block()
        stripped = ih.strip_existing(combined)
        self.assertEqual(stripped, base)


class FindGitDirTests(unittest.TestCase):
    """A-04：worktree / submodule 的 .git 是**文件**，钩子必须落到真正生效的 git 目录。

    修复前 `if os.path.isfile(cand): return None` 直接把这两类仓库判成"找不到 git 仓库"。
    worktree 还有个更隐蔽的点：钩子装在**公共**目录（主仓库 .git/hooks），
    写进 .git/worktrees/<名字>/hooks 是白写——git 用 commondir 文件记录这层跳转。
    """

    def setUp(self):
        import shutil
        self.tmp = tempfile.mkdtemp(prefix="tsc-gitdir-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def _make_worktree(self):
        """返回 (worktree 路径, 公共 .git 目录) 的伪布局。"""
        common = os.path.join(self.tmp, "main", ".git")
        wt_git = os.path.join(common, "worktrees", "feat")
        self._write(os.path.join(wt_git, "commondir"), "../..\n")
        wt = os.path.join(self.tmp, "wt")
        self._write(os.path.join(wt, ".git"), "gitdir: %s\n" % wt_git.replace("\\", "/"))
        return wt, common

    def test_plain_repo_returns_dot_git(self):
        import install_hook as ih
        repo = os.path.join(self.tmp, "repo")
        os.makedirs(os.path.join(repo, ".git", "hooks"))
        self.assertEqual(ih.find_git_dir(repo), os.path.join(repo, ".git"))

    def test_worktree_resolves_to_common_dir(self):
        import install_hook as ih
        wt, common = self._make_worktree()
        self.assertEqual(ih.find_git_dir(wt), os.path.normpath(common))

    def test_submodule_resolves_to_modules_dir(self):
        # submodule 的 .git 也是文件，但 Git 目录在 .git/modules/<name>，且没有 commondir
        import install_hook as ih
        modules = os.path.join(self.tmp, "super", ".git", "modules", "sub")
        os.makedirs(modules)
        sub = os.path.join(self.tmp, "super", "sub")
        self._write(os.path.join(sub, ".git"), "gitdir: %s\n" % modules.replace("\\", "/"))
        self.assertEqual(ih.find_git_dir(sub), os.path.normpath(modules))

    def test_broken_gitdir_pointer_is_none(self):
        import install_hook as ih
        repo = os.path.join(self.tmp, "broken")
        self._write(os.path.join(repo, ".git"), "gitdir: /nonexistent/nowhere\n")
        self.assertIsNone(ih.find_git_dir(repo))

    def test_missing_dir_is_none(self):
        import install_hook as ih
        self.assertIsNone(ih.find_git_dir(os.path.join(self.tmp, "nope")))

    def test_hook_lands_in_common_dir_for_worktree(self):
        """端到端：在 worktree 上装钩子，文件出现在公共 .git/hooks/pre-commit。"""
        import install_hook as ih
        wt, common = self._make_worktree()
        self.assertEqual(ih.main(["--repo", wt]), 0)
        self.assertTrue(os.path.isfile(os.path.join(common, "hooks", "pre-commit")))
        # 幂等卸载
        self.assertEqual(ih.main(["--repo", wt, "--uninstall"]), 0)
        self.assertFalse(os.path.exists(os.path.join(common, "hooks", "pre-commit")))


class ConsoleEncodingTests(unittest.TestCase):
    """控制台不是 UTF-8 时，中文输出不能把进程带崩。

    这是 CI（Windows runner）抓到的真实缺陷：这些脚本的输出全是中文，而英文版
    Windows 的控制台/管道编码是 **cp1252**，`print("已安装...")` 直接抛
    `UnicodeEncodeError: 'charmap' codec can't encode ...`，进程以 rc=1 退出——
    安装动作其实已经成功落盘，调用方却以为失败了。

    ⚠️ 本机是 cp936（能编码中文），本地怎么跑都不报；必须显式把子进程的
    PYTHONIOENCODING 压成 cp1252 才复现得出来。这也是"加多平台 CI"的价值所在。
    """

    def _env(self):
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "cp1252"
        return env

    def _run(self, *args):
        return subprocess.run([sys.executable] + list(args), capture_output=True,
                              env=self._env())

    def test_guard_selftest_survives_non_utf8_console(self):
        rc = self._run(os.path.join(SCRIPTS, "structure_guard.py"), "--selftest")
        self.assertEqual(rc.returncode, 0, rc.stderr.decode("utf-8", "replace")[-400:])

    def test_guard_report_survives_non_utf8_console(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "bad.py")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("x = (1\n")
            rc = self._run(os.path.join(SCRIPTS, "structure_guard.py"), p, "--color", "never")
            self.assertEqual(rc.returncode, 1, rc.stderr.decode("utf-8", "replace")[-400:])

    def test_hook_mode_survives_non_utf8_console(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "bad.py")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("x = (1\n")
            rc = subprocess.run(
                [sys.executable, os.path.join(SCRIPTS, "structure_guard.py"), "--from-hook"],
                input=json.dumps({"tool_input": {"file_path": p}}),
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                env=self._env())
            self.assertEqual(rc.returncode, 2, rc.stderr[-400:])

    def test_install_hook_survives_non_utf8_console(self):
        with tempfile.TemporaryDirectory() as d:
            repo = os.path.join(d, "repo")
            os.makedirs(os.path.join(repo, ".git", "hooks"))
            rc = self._run(os.path.join(SCRIPTS, "install_hook.py"), "--repo", repo)
            self.assertEqual(rc.returncode, 0, rc.stderr.decode("utf-8", "replace")[-400:])

    def test_bracket_lint_selftest_survives_non_utf8_console(self):
        rc = self._run(os.path.join(SCRIPTS, "bracket_lint.py"), "--selftest")
        self.assertEqual(rc.returncode, 0, rc.stderr.decode("utf-8", "replace")[-400:])


class SupportedFileTests(unittest.TestCase):
    def test_powershell_extensions(self):
        self.assertTrue(sg.is_supported_file("test.ps1"))
        self.assertTrue(sg.is_supported_file("test.psm1"))
        self.assertTrue(sg.is_supported_file("test.psd1"))

    def test_extensionless_script_with_shebang(self):
        with tempfile.TemporaryDirectory() as d:
            p_script = os.path.join(d, "run-tool")
            with open(p_script, "w", encoding="utf-8") as f:
                f.write("#!/usr/bin/env python3\nprint('hello')\n")
            p_text = os.path.join(d, "notes")
            with open(p_text, "w", encoding="utf-8") as f:
                f.write("just a note\n")
            self.assertTrue(sg.is_supported_file(p_script))
            self.assertFalse(sg.is_supported_file(p_text))

    def test_install_hook_collision_message(self):
        import install_hook as ih
        with tempfile.TemporaryDirectory() as d:
            repo = os.path.join(d, "repo")
            hook_dir = os.path.join(repo, ".git", "hooks")
            os.makedirs(hook_dir)
            hook_file = os.path.join(hook_dir, "pre-commit")
            with open(hook_file, "w", encoding="utf-8") as f:
                f.write("#!/usr/bin/env bash\n# File generated by pre-commit: https://pre-commit.com\nexit 0\n")
            rc = ih.main(["--repo", repo])
            self.assertEqual(rc, 2)


class StrictModeTests(unittest.TestCase):
    """false-green 回归：没真正完成检查，就不能显示全绿。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sg-strict-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _write(self, rel, text):
        p = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
        return p

    def test_over_1000_files_truncated_strict_fails(self):
        # 1000 个好文件 + 第 1001 个坏文件（排序在截断范围之外）
        for i in range(1000):
            self._write("f%04d.py" % i, "x = 1\n")
        self._write("zz_bad.py", "x = (1\n")
        rc_non_strict = sg.main([self.tmp, "--quiet", "--color", "never"])
        self.assertEqual(rc_non_strict, 0, "非严格模式保持本地告警语义（见 stderr 警告）")
        rc_strict = sg.main([self.tmp, "--strict", "--quiet", "--color", "never"])
        self.assertEqual(rc_strict, 2, "严格模式下截断 = 没查完 ≠ 通过")

    def test_over_2mb_file_degraded_strict_fails(self):
        # >2MB 的语法错误文件：L2 被跳过（只有 L1），严格模式必须拦"降级"
        big = "# " + "a" * (2 * 1024 * 1024) + "\nx = 1 + * 2\n"
        self._write("big.py", big)
        rc_non_strict = sg.main([self.tmp, "--quiet", "--color", "never"])
        self.assertEqual(rc_non_strict, 0)
        rc_strict = sg.main([self.tmp, "--strict", "--quiet", "--color", "never"])
        self.assertEqual(rc_strict, 2)

    def test_big_file_bracket_error_still_fails_l1(self):
        big = "# " + "a" * (2 * 1024 * 1024) + "\nx = (1\n"
        self._write("big.py", big)
        self.assertEqual(sg.main([self.tmp, "--strict", "--quiet", "--color", "never"]), 1)

    def test_exit_code_for_strict_matrix(self):
        ok = [{"issues": [], "degraded": [], "tool_error": None}]
        deg_tool = [{"issues": [], "degraded": ["node 不可用，JS 仅做平衡检查"],
                     "tool_error": None}]
        deg_big = [{"issues": [], "degraded": ["超大文件(>2MB)，仅做 L0/L1 平衡检查"],
                    "tool_error": None}]
        bad = [{"issues": [1], "degraded": [], "tool_error": None}]
        self.assertEqual(sg.exit_code_for(ok, strict=True), 0)
        self.assertEqual(sg.exit_code_for(deg_tool, strict=True), 2)
        self.assertEqual(sg.exit_code_for(deg_tool, strict=True, allow_missing_tools=True), 0)
        self.assertEqual(sg.exit_code_for(deg_big, strict=True, allow_missing_tools=True), 2)
        self.assertEqual(sg.exit_code_for(deg_tool, strict=False), 0)  # 本地模式只告警
        self.assertEqual(sg.exit_code_for(bad, strict=True), 1)        # 代码问题优先
        self.assertEqual(sg.exit_code_for(ok, strict=True, truncated=5), 2)

    def test_degraded_kind_classification(self):
        self.assertEqual(sg.degraded_kind("node 不可用，JS 仅做平衡检查"), "missing-tool")
        self.assertEqual(sg.degraded_kind("无 PyYAML，.yaml 仅做平衡检查"), "missing-tool")
        self.assertEqual(sg.degraded_kind("超大文件(>2MB)，仅做 L0/L1 平衡检查"), "big-file")
        self.assertEqual(sg.degraded_kind("未知语言 xyz，按 plain 处理"), "unknown-lang")
        self.assertEqual(sg.degraded_kind("未来某类降级"), "other")

    def test_strict_blocks_big_file_even_with_allow_missing_tools(self):
        big = "# " + "a" * (2 * 1024 * 1024) + "\nx = 1\n"
        self._write("big.py", big)
        rc = sg.main([self.tmp, "--strict", "--allow-missing-tools",
                      "--quiet", "--color", "never"])
        self.assertEqual(rc, 2, "--allow-missing-tools 只放行工具缺席，不放行大文件降级")

    def test_clean_small_project_strict_passes(self):
        self._write("a.py", "x = 1\n")
        self.assertEqual(sg.main([self.tmp, "--strict", "--allow-missing-tools",
                                  "--quiet", "--color", "never"]), 0)


class SubprocessVerdictTests(unittest.TestCase):
    """子进程判定以退出码为准：stderr 有内容但 rc=0 的合法命令不得误判失败。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sg-rc-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_rc0_with_stderr_warning_passes(self):
        from unittest import mock
        target = os.path.join(self.tmp, "a.sh")
        with open(target, "w", encoding="utf-8") as fh:
            fh.write("echo hi\n")
        fake = (0, "", "deprecation warning: something benign", None)
        with mock.patch.object(sg, "_run_cmd", return_value=fake):
            issue, terr, deg = sg.check_bash(target, "echo hi\n")
        self.assertIsNone(issue, "rc=0 + stderr warning 不是失败")
        self.assertIsNone(terr)

    def test_rc_nonzero_still_fails(self):
        from unittest import mock
        target = os.path.join(self.tmp, "a.sh")
        with open(target, "w", encoding="utf-8") as fh:
            fh.write("if true\n")
        fake = (2, "", "a.sh: line 1: syntax error near unexpected token `fi'\n", None)
        with mock.patch.object(sg, "_run_cmd", return_value=fake):
            issue, terr, deg = sg.check_bash(target, "if true\n")
        self.assertIsNotNone(issue)
        self.assertEqual(issue["code"], "syntax-error")


class GuardSkipStringLiteralTests(unittest.TestCase):
    """guard:skip 只有在真实注释上下文才生效，字符串字面量里的不算。"""

    def test_marker_in_string_does_not_exempt(self):
        res = sg.check_source("a.py", 'x = ("guard:skip"\n', real_file=False)
        self.assertFalse(res["ok"], "字符串里的 guard:skip 不得豁免该行问题")
        self.assertEqual(res["exempted"], 0)

    def test_marker_in_real_comment_exempts(self):
        res = sg.check_source("a.py", "x = (1  # guard:skip\n", real_file=False)
        self.assertTrue(res["ok"])
        self.assertGreaterEqual(res["exempted"], 1)  # 该行所有问题一并豁免

    def test_marker_in_string_before_comment_not_exempt(self):
        # 同一行里既有含标记的字符串又有真注释（注释里没有标记）→ 不豁免
        res = sg.check_source("a.py", 'x = ("guard:skip"  # note\n', real_file=False)
        self.assertFalse(res["ok"])

    def test_marker_after_hash_inside_string_not_exempt(self):
        res = sg.check_source("a.py", 's = "a#guard:skip"\nx = (1\n', real_file=False)
        self.assertFalse(res["ok"], "字符串内的 # 不是注释起点")

    def test_lisp_comment_marker_exempts(self):
        res = sg.check_source(
            "a.lsp", "(defun f (x)\n  (setq y x 2)  ; guard:skip=setq-odd-args\n  (list y))\n",
            real_file=False)
        self.assertTrue(res["ok"])


class HookTruncationTests(unittest.TestCase):
    """闸1 hook 文件数截断必须显性告警，不得静默。"""

    def _run_hook(self, stdin_text):
        return subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "structure_guard.py"), "--from-hook"],
            input=stdin_text, capture_output=True, text=True,
            encoding="utf-8", errors="replace")

    def test_many_files_warn_truncation_but_fail_open(self):
        with tempfile.TemporaryDirectory() as d:
            paths = []
            for i in range(sg.MAX_HOOK_FILES + 5):
                p = os.path.join(d, "f%02d.py" % i)
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write("x = 1\n")
                paths.append(p)
            proc = self._run_hook(json.dumps({"tool_input": {"file_path": paths}}))
            self.assertEqual(proc.returncode, 0, "fail-open 契约：截断不拦截")
            self.assertIn("超过上限", proc.stderr, "但必须显性告警，不得静默截断")

    def test_bad_file_within_limit_still_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "bad.py")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("x = (1\n")
            proc = self._run_hook(json.dumps({"tool_input": {"file_path": [p]}}))
            self.assertEqual(proc.returncode, 2)


class GuardAssertsSecurityTests(unittest.TestCase):
    """A-01（P0）：仓库里的 guard_asserts.py 绝不自动执行；只有显式 --asserts 才加载。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sg-l4-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _write(self, rel, text):
        p = os.path.join(self.tmp, rel)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
        return p

    def test_repo_asserts_not_loaded_by_default(self):
        """PR 塞进仓库根的 guard_asserts.py 不得在开发者 commit 时被执行。"""
        marker = os.path.join(self.tmp, "pwned.txt")
        self._write("a.py", "x = 1\n")
        self._write("guard_asserts.py",
                    "import os\n"
                    "def run(paths):\n"
                    "    with open(r'%s', 'w') as fh:\n"
                    "        fh.write('executed')\n"
                    "    return []\n" % marker.replace("\\", "\\\\"))
        rc = sg.main([self.tmp, "--quiet", "--color", "never"])
        self.assertEqual(rc, 0)
        self.assertFalse(os.path.exists(marker), "默认加载路径绝不能执行仓库里的断言文件")

    def test_explicit_asserts_flag_loads(self):
        """显式 --asserts <路径> = 运维者授权，此时正常加载并运行 L4。"""
        self._write("a.py", "x = 1\n")
        asserts = self._write("my_asserts.py",
                              "def run(paths):\n"
                              "    return [('a.py', 1, 'L4 hit')]\n")
        rc = sg.main([self.tmp, "--quiet", "--color", "never", "--asserts", asserts])
        self.assertEqual(rc, 1, "L4 断言报出的条目按代码问题拦截")

    def test_missing_asserts_path_is_tool_error(self):
        self._write("a.py", "x = 1\n")
        rc = sg.main([self.tmp, "--quiet", "--color", "never",
                      "--asserts", os.path.join(self.tmp, "nope.py")])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()

