# -*- coding: utf-8 -*-
"""structure_guard 单元测试 —— 门禁自身的回归防线（检查器坏了比没有更危险）。

覆盖：check_source 分层判定（L1/L2/L3/跳过）、退出码优先级、CLI 行为、
闸1 hook 模式（拦截/放行/fail-open）、目录扫描过滤、钩子安装器指向。
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(ROOT, "scripts")
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
        for rel in ("scripts/bracket_lint.py", "scripts/install_hook.py", "scripts/structure_guard.py"):
            self.assertEqual(sg.main([os.path.join(ROOT, rel), "--quiet",
                                      "--color", "never"]), 0, rel)

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
        text = src_of("scripts/install_hook.py")
        self.assertIn("structure_guard.py", text)
        self.assertIn("--staged", text)

    def test_hook_blocks_only_on_exit_1(self):
        text = src_of("scripts/install_hook.py")
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


if __name__ == "__main__":
    unittest.main()
