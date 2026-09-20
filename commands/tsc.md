---
description: TSC 总入口：默认查看状态；说"接入/同步/升级"时按对应流程走
---

TSC 总入口。先执行
`python3 <本插件根>/scripts/tsc.py status --project <当前项目根>` 与
`python3 <本插件根>/scripts/tsc.py doctor --project <当前项目根>`，
汇报现状；然后按 $ARGUMENTS 里的诉求路由：

- "接入契约" / "安装契约" → /tsc-sync 的 install 流程（先 `install --dry-run` 预览，确认后真跑，再按 BOOTSTRAP 探测填 §2 与 `.agents/project.py`，最后 `check-config` + `verify` + `doctor`）
- "同步契约" / "更新契约" → /tsc-sync
- "更新 TSC" / "升级 TSC" → /tsc-update
- "升级 TSC，并同步当前项目" → 先 /tsc-update，再 /tsc-sync，最后 `check-config` + `verify`，汇报完整升级链
- "回滚契约" → `python3 <本插件根>/scripts/tsc.py rollback --project <当前项目根>`
- "体检" / "audit" → 读本插件的 `skills/tsc/references/AUDIT-SPEC.md`，只读扫描后停下等确认
