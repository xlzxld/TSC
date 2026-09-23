# -*- coding: utf-8 -*-
"""bracket_lint 内置自检并入 unittest 门禁（方案 P0 项：检查器自身必须最高频受检）。"""
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(ROOT, "skills", "tsc", "scripts")
sys.path.insert(0, SCRIPTS)

import bracket_lint  # noqa: E402


def scan(src, lang="js"):
    sc = bracket_lint.Scanner(src, bracket_lint.PROFILES[lang], "<%s>" % lang)
    sc.run()
    return sc


class BracketLintSelftestTests(unittest.TestCase):
    def test_builtin_selftest_green(self):
        rc = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "bracket_lint.py"), "--selftest"],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(rc.returncode, 0, rc.stdout + rc.stderr)


class JsInterpolationBoundaryTests(unittest.TestCase):
    """A-08：插值内的引号扫描越界，把**合法**的 JS 误报成结构错误。

    根因：`_scan_interp` 只认 " 与 '，不认正则字面量与注释。`replace(/'/g, "")`
    里那个 `'` 被当成字符串开头，扫描一路吃到 EOF，顺手吞掉插值的闭 `}`，
    于是外层认定 backtick 没闭合、括号没闭合——实测一个完全合法的 .js 报 3 处。

    修复要点：插值内按 JS 词法先跳注释、再按主扫描同款判据识别正则，并给引号串
    加"裸换行即中止"的边界。注意这里刻意**不**对未闭合串额外报错：歧义时只停住
    不误报，真坏的代码由 L2（node --check / ast）兜底，符合本工程"误报优先于漏报"的口径。
    """

    def test_regex_with_quote_in_interpolation_is_clean(self):
        src = 'const out = `${items.map(s => s.replace(/\'/g, "")).join(",")}`;\n'
        sc = scan(src)
        self.assertTrue(sc.ok, sc.issues)
        self.assertEqual(sc.stack, [])

    def test_comment_with_quote_in_interpolation_is_clean(self):
        self.assertTrue(scan("const t = `${ /* don't */ x }`;\n").ok)

    def test_line_comment_in_interpolation_is_clean(self):
        self.assertTrue(scan("const t = `${ 1 // don't\n}`;\n").ok)

    def test_division_in_interpolation_is_not_a_regex(self):
        self.assertTrue(scan("const u = `${a / 2}`;\n").ok)
        self.assertTrue(scan("const v = `${(a + b) / 2}`;\n").ok)

    def test_nested_template_still_clean(self):
        self.assertTrue(scan('const t = `${a.map((p) => `<o v="${p.id}">${p.k}</o>`)}`;\n').ok)

    def test_cross_line_string_in_interpolation_is_left_to_L2(self):
        """L1 对插值内缺配对的引号只停住、不报错——这是刻意的层级分工。

        L1 只做括号平衡。若在这里报"字符串没闭合"，合法 JSX 文案里的撇号
        （`` `${<Foo>don't</Foo>}` ``）就会被误伤；本工程的口径是误报优先于漏报，
        真语法问题交给 L2（ast / node --check）。此处把这条口径固定下来。
        """
        self.assertTrue(scan('const t = `${ "abc\n}`;\n').ok)

    def test_unbalanced_inside_interpolation_is_still_caught(self):
        self.assertFalse(scan("const x = `${f(}`;\n").ok)

    def test_later_real_problem_is_still_detected(self):
        """修复不能靠"跳过插值后面的一切"来实现：插值之后的真问题仍须被发现。"""
        src = 'const out = `${s.replace(/\'/g, "")}`;\nfunction f() {\n  return 1;\n'
        sc = scan(src)
        self.assertFalse(sc.ok)
        self.assertTrue(
            sc.stack, "插值后面少写的右花括号没被发现——说明插值扫描吞掉了后续内容")


if __name__ == "__main__":
    unittest.main()
