---
description: 把 TSC 契约同步到当前项目（只更新项目契约，不联网）
---

同步当前项目契约：先跑
`python3 <本插件根>/scripts/tsc.py sync --project <当前项目根> --dry-run`
把将发生的改动报给用户；确认后去掉 `--dry-run` 真跑，随后执行 `check-config`，并汇报版本变化与退出码。

安全规则：只从当前已安装的 TSC 本体取内容；项目 AGENTS.md 缺 `tsc-managed-contract` 标记时脚本会拒绝接管并输出冲突摘要——此时原样转述给用户，等用户确认后改用 `install --force`。

$ARGUMENTS
