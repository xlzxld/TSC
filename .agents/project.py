# -*- coding: utf-8 -*-
"""本项目（TSC 插件仓库自己）的门禁命令（tsc.py verify 按顺序执行这 4 条）。

本文件是"项目自己的门禁命令"，上游永不覆盖；与根 AGENTS.md §2 必须同源
（check-config 校验）。新项目接入时由 templates/project.example.py 生成。
"""

__all__ = ["FMT_CHECK_CMD", "LINT_CMD", "TEST_CMD", "BUILD_CMD"]

# 格式化检查：必须是 --check 等价命令，禁止写会改文件的写模式
FMT_CHECK_CMD = None

# 静态检查：结构门禁（正本在插件 scripts/ 目录）
LINT_CMD = "python3 scripts/structure_guard.py --quiet --color never ."

# 测试（unit + e2e；只跑快层用 -s tests/unit）
TEST_CMD = 'python3 -m unittest discover -s tests -p "test_*.py"'

# 构建
BUILD_CMD = None
