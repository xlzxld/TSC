---
description: 更新 TSC 本体（git pull 技能目录；非 git 安装走宿主更新）
---

更新 TSC 技能本体：执行
`python3 <技能根>/scripts/tsc.py update`
并汇报版本变化（旧 → 新）与退出码。

注意：只更新本体，**不要**顺手同步项目契约；用户要同步项目时用 /tsc-sync，或明说"升级 TSC，并同步当前项目"一次完成两步。非 git 安装副本（如宿主插件/技能管理安装）会提示走宿主平台的插件/技能管理页更新，原样转述即可。

$ARGUMENTS
