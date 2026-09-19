# -*- coding: utf-8 -*-
"""本项目自己的门禁命令（tsc.py verify 会按顺序执行这里登记的 4 条命令）。

安装时由 tsc.py 从本文件复制生成 project.py；生成后**上游永远不会覆盖它**。
把下面四条改成你项目真实的命令即可；没有的项写 None。

平台差异集中在这里，例如 macOS 一般要写 python3、Windows 写 python：
    import sys
    PY = "python" if sys.platform == "win32" else "python3"
    TEST_CMD = f"{PY} -m pytest"

注意：AGENTS.md 的 §2 表格与这里必须保持一致，否则 check-config 会报错。
"""

__all__ = ["FMT_CHECK_CMD", "LINT_CMD", "TEST_CMD", "BUILD_CMD"]

# 格式化检查：必须是 --check 等价命令，禁止写会改文件的写模式
FMT_CHECK_CMD = None

# 静态检查：结构门禁（母版正本在仓库根；下游项目用落盘件 .agents/structure_guard.py）
LINT_CMD = "python structure_guard.py --quiet --color never ."

# 测试（macOS 上如无 python 命令，此处与 AGENTS.md §2 同步改成 python3）
TEST_CMD = 'python -m unittest discover -s .agents/test -p "test_*.py"'

# 构建
BUILD_CMD = None
