---
description: TSC 契约状态一览（接入、版本、所有权、§2、门禁）
---

查看 TSC 状态：对当前工作区执行
`python3 <本插件根>/scripts/tsc.py status --project <当前项目根>` 与
`python3 <本插件根>/scripts/tsc.py doctor --project <当前项目根>`，
把接入状态、所有权、契约版本与上游版本、§2 是否填好、门禁可跑、doctor 的 ready/not-ready 结论汇报给用户。只读，不写任何文件。

$ARGUMENTS
