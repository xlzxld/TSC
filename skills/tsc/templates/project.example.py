# -*- coding: utf-8 -*-
"""本项目自己的门禁命令（tsc.py verify 会按顺序执行这里登记的 4 条命令）。

安装时由 tsc.py 从本文件复制生成 project.py；生成后**上游永远不会覆盖它**。
把下面四条改成你项目真实的命令即可；没有的项写 None。

命令格式说明：
    - 直接写项目通用命令（如 python3 -m pytest -q 或 npm test）。
    - 跨平台兼容：若首令牌 python/python3 在当前系统 PATH 中不存在，tsc.py verify 会自动回退到当前解释器执行，无需手工拼接 sys.executable。
    - 注意：AGENTS.md 的 §2 表格与这里登记的命令字面量必须保持完全一致，否则 check-config 会报错。
"""

__all__ = ["FMT_CHECK_CMD", "LINT_CMD", "TEST_CMD", "BUILD_CMD"]

# 格式化检查：必须是 --check 等价命令，禁止写会改文件的写模式
FMT_CHECK_CMD = None

# 静态检查
LINT_CMD = None

# 测试
TEST_CMD = None

# 构建
BUILD_CMD = None
