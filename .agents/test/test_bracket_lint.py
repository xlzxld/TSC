# -*- coding: utf-8 -*-
"""bracket_lint 内置自检并入 unittest 门禁（方案 P0 项：检查器自身必须最高频受检）。"""
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class BracketLintSelftestTests(unittest.TestCase):
    def test_builtin_selftest_green(self):
        rc = subprocess.run(
            [sys.executable, os.path.join(ROOT, "bracket_lint.py"), "--selftest"],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(rc.returncode, 0, rc.stdout + rc.stderr)


if __name__ == "__main__":
    unittest.main()
