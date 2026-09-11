#!/bin/sh
# 系统入口薄壳（macOS / Linux）：找到 Python 并转交 tsc.py verify
# 本脚本常驻技能目录。默认对"当前目录"跑门禁——cd 到项目里再执行它即可；
# 参数透传给 verify（如 --project <路径>）。
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
py=$(command -v python3 || command -v python)
if [ -z "$py" ]; then
  echo "未找到 Python。macOS 可执行：xcode-select --install"
  exit 3
fi
exec "$py" "$here/tsc.py" verify "$@"
