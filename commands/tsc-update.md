---
description: 更新 TSC 本体（git pull 插件目录；非 git 安装走宿主更新）
---

更新 TSC 技能/插件本体：执行
`python3 <本插件根>/scripts/tsc.py update`
并汇报版本变化（旧 → 新）与退出码。

注意：只更新本体，**不要**顺手同步项目契约；用户要同步项目时用 /tsc-sync，或明说"升级 TSC，并同步当前项目"一次完成两步。非 git 安装副本（如宿主插件市场安装）会提示走 ZCode 设置 → 插件管理 → 更新，原样转述即可。

$ARGUMENTS
