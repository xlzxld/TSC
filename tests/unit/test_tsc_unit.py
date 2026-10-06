# -*- coding: utf-8 -*-
"""tsc.py 单元测试（进程内，不跑子进程安装，目标 <10s）。

覆盖：
- §2 切分 / 合成保真 / 结构签名 / 占位化
- 路径归一（Git Bash 的 /c/... 风格）
- 上游解析：显式 --source > 当前已安装本体；.source 绝不参与选源（P1-01）
- .source 结构化 provenance：JSON 读写、旧版纯路径文本兼容（P2-08）
- AGENTS.md 所有权：none / managed / legacy / foreign（P1-03）
- 执法包归属三态 + Node/JS 探测（Python-only 项目不部署 commitlint，P1-04）
- 门禁命令超时：杀进程组、返回 124（P1-05）
- 技能打包：目录自包含 + 平台中立 + SKILL.md frontmatter（P1-02 通用化、P2-01）
- 模板约束：所有权标记、gitleaks 钉 SHA（P2-06）、gate.yml commitlint 条件、内外 AGENTS.md 零漂移
"""

import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SKILL = REPO / "skills" / "tsc"
sys.path.insert(0, str(SKILL / "scripts"))

# 跨平台门禁夹具：绝不写 `true` / `sleep` 这类 POSIX 专属命令——
# Windows 上根本没有它们，会让超时相关的用例在 Windows 上必然失败（A-02）。
QUICK_CMD = '"%s" -c "pass"' % sys.executable
SLOW_CMD = '"%s" -c "import time;time.sleep(60)"' % sys.executable

import tsc  # noqa: E402

# 与模板 §2 同构的样例（主干分支取 master，用于验证分支名跟随）
AGENTS_SAMPLE = """# 标题

<!-- tsc-managed-contract:v4 -->

> 头注

## 1. 行为契约

- 规则一

## 2. 项目环境与验证门禁

| 项 | 命令 / 取值 | 验证条件 |
|---|---|---|
| 技术栈 | Demo | — |
| 构建 (Build) | 无 | — |
| 测试 (Test) | pytest | ✅ 全绿 |
| 静态检查 (Lint) | ruff | ✅ 0 错误 |
| 格式化 (Format) | black --check | ✅ 0 差异 |
| 主干分支 | master | ✅ 禁止直推 |
| 已知豁免清单 | 无 | 白名单 |

> 尾注

## 3. 红线

内容
"""


class Section2Tests(unittest.TestCase):
    def test_span_and_text(self):
        span = tsc.section2_span(AGENTS_SAMPLE)
        self.assertIsNotNone(span)
        block = tsc.section2_text(AGENTS_SAMPLE)
        self.assertIn("## 2.", block)
        self.assertNotIn("## 3.", block)
        self.assertIn("主干分支", block)

    def test_compose_preserves_project_section2(self):
        project = AGENTS_SAMPLE.replace("| 测试 (Test) | pytest |", "| 测试 (Test) | pytest -q |")
        merged = tsc.compose_agents_md(AGENTS_SAMPLE, project)
        self.assertIn("| 测试 (Test) | pytest -q |", merged)
        self.assertIn("> 尾注", merged)  # §2 之外的行来自上游

    def test_signature_detects_label_and_column_drift(self):
        up_cols, up_labels = tsc.section2_signature(tsc.section2_text(AGENTS_SAMPLE))
        shrunk = AGENTS_SAMPLE.replace("| 格式化 (Format) | black --check | ✅ 0 差异 |\n", "")
        _, pr_labels = tsc.section2_signature(tsc.section2_text(shrunk))
        missing = [lab for lab in up_labels if lab not in pr_labels]
        self.assertEqual(missing, ["格式化 (Format)"])
        drifted = AGENTS_SAMPLE.replace(
            "| 项 | 命令 / 取值 | 验证条件 |", "| 项 | 命令 / 取值 |"
        )
        dr_cols, _ = tsc.section2_signature(tsc.section2_text(drifted))
        self.assertNotEqual(len(up_cols), len(dr_cols))

    def test_split_table_row_keeps_escaped_pipe(self):
        cells = tsc.split_table_row("| a | b \\| c | d |")
        self.assertEqual(cells, ["a", "b \\| c", "d"])
        self.assertEqual(tsc.unescape_cell(cells[1]), "b | c")
        self.assertEqual(
            tsc.split_table_row("| 项 | 命令 / 取值 | 验证条件 |"),
            ["项", "命令 / 取值", "验证条件"])

    def test_placeholder_skips_header_without_magic_label(self):
        sample = AGENTS_SAMPLE.replace(
            "| 项 | 命令 / 取值 | 验证条件 |", "| 名称 | 值 | 说明 |"
        )
        out = tsc.section2_to_placeholder(sample)
        self.assertIn("| 名称 | 值 | 说明 |", out)
        self.assertIn("| 测试 (Test) | [自动填充] |", out)

    def test_normalize_path_passthrough(self):
        self.assertEqual(tsc.normalize_path_arg("C:/foo/bar"), "C:/foo/bar")
        self.assertEqual(tsc.normalize_path_arg("/tmp/normal"), "/tmp/normal")


class OwnershipTests(unittest.TestCase):
    """P1-03：所有权只认 marker / TSC 部署证据，绝不凭 §2 形状。"""

    def setUp(self):
        import shutil
        self.tmp = Path(tempfile.mkdtemp(prefix="tsc-own-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_no_agents_md_is_none(self):
        self.assertEqual(tsc.contract_ownership(self.tmp), "none")

    def test_marker_is_managed(self):
        (self.tmp / "AGENTS.md").write_text(AGENTS_SAMPLE, encoding="utf-8")
        self.assertEqual(tsc.contract_ownership(self.tmp), "managed")

    def test_version_file_with_tsc_evidence_is_legacy(self):
        """legacy 需要 ≥2 个独立 TSC 历史特征：合法历史版本号 + 部署痕迹。"""
        (self.tmp / "AGENTS.md").write_text(AGENTS_SAMPLE.replace(
            "<!-- tsc-managed-contract:v4 -->\n\n", ""), encoding="utf-8")
        (self.tmp / ".agents").mkdir()
        (self.tmp / ".agents" / "VERSION").write_text("3.3.2\n", encoding="utf-8")
        # 特征 B：.agents/.source（TSC install 必写的 provenance）
        (self.tmp / ".agents" / ".source").write_text("/old/skill\n", encoding="utf-8")
        self.assertEqual(tsc.contract_ownership(self.tmp), "legacy")

    def test_version_file_alone_is_foreign(self):
        """只有 .agents/VERSION（哪怕格式合法）≠ TSC 项目：凑不齐两个特征按 foreign。"""
        (self.tmp / "AGENTS.md").write_text(AGENTS_SAMPLE.replace(
            "<!-- tsc-managed-contract:v4 -->\n\n", ""), encoding="utf-8")
        (self.tmp / ".agents").mkdir()
        (self.tmp / ".agents" / "VERSION").write_text("3.3.2\n", encoding="utf-8")
        self.assertEqual(tsc.contract_ownership(self.tmp), "foreign")

    def test_version_and_legacy_files_is_legacy(self):
        """特征 B 的另一形态：根目录残留旧版契约文件（AUDIT-SPEC.md）。"""
        (self.tmp / "AGENTS.md").write_text(AGENTS_SAMPLE.replace(
            "<!-- tsc-managed-contract:v4 -->\n\n", ""), encoding="utf-8")
        (self.tmp / ".agents").mkdir()
        (self.tmp / ".agents" / "VERSION").write_text("3.3.2\n", encoding="utf-8")
        (self.tmp / "AUDIT-SPEC.md").write_text("# old\n", encoding="utf-8")
        self.assertEqual(tsc.contract_ownership(self.tmp), "legacy")

    def test_plain_agents_md_is_foreign(self):
        # 外部项目自己的规范：像 §2 也不行——没有 marker、没有 TSC 部署证据
        (self.tmp / "AGENTS.md").write_text(
            AGENTS_SAMPLE.replace("<!-- tsc-managed-contract:v4 -->\n\n", ""),
            encoding="utf-8")
        self.assertEqual(tsc.contract_ownership(self.tmp), "foreign")

    def test_prose_mention_is_not_managed(self):
        """"提及"标记字符串 ≠ "声明"托管：判错会把外部规范当托管文件重建覆盖。"""
        mentioned = AGENTS_SAMPLE.replace(
            "<!-- tsc-managed-contract:v4 -->\n\n", "").replace(
            "> 头注",
            "> 头注：TSC 托管的契约带 `<!-- tsc-managed-contract:v4 -->` 标记；\n"
            "> 本文件不用 tsc-managed-contract 托管。", 1)
        self.assertIn(tsc.CONTRACT_MARKER, mentioned)  # 前置：正文里确实出现了该字符串
        (self.tmp / "AGENTS.md").write_text(mentioned, encoding="utf-8")
        self.assertEqual(tsc.contract_ownership(self.tmp), "foreign")

    def test_template_and_root_agents_carry_marker(self):
        for rel in ("skills/tsc/templates/AGENTS.md", "AGENTS.md"):
            text = tsc.read_text(REPO / rel)
            self.assertIn(tsc.CONTRACT_MARKER_LINE, text, rel)

    def test_root_agents_is_compose_of_template(self):
        """本仓库根 AGENTS.md 必须与模板零漂移（§2 取值除外）——防止两份母版分叉。"""
        template = tsc.read_text(SKILL / "templates/AGENTS.md")
        root = tsc.read_text(REPO / "AGENTS.md")
        self.assertEqual(tsc.compose_agents_md(template, root), root)


class UpstreamResolutionTests(unittest.TestCase):
    """P1-01：来源优先级 = 显式 --source > 当前已安装本体；.source 只是记录。"""

    def setUp(self):
        import shutil
        self.tmp = Path(tempfile.mkdtemp(prefix="tsc-up-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_explicit_source_wins(self):
        self.assertEqual(tsc.find_upstream(str(self.tmp)), self.tmp.resolve())

    def test_default_is_installed_plugin_root(self):
        self.assertEqual(tsc.find_upstream(None), tsc.upstream_root())
        self.assertEqual(tsc.upstream_root(), SKILL)

    def test_validate_upstream_new_layout(self):
        self.assertEqual(tsc.validate_upstream(SKILL), [])
        missing = tsc.validate_upstream(self.tmp)
        self.assertIn(tsc.VERSION_FILE, missing)
        self.assertIn(tsc.TEMPLATE_AGENTS, missing)


class SourceRecordTests(unittest.TestCase):
    """P2-08：结构化 provenance；旧版纯路径文本兼容读取。"""

    def setUp(self):
        import shutil
        self.tmp = Path(tempfile.mkdtemp(prefix="tsc-src-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / ".agents").mkdir()

    def test_write_and_read_json_record(self):
        skill = Path("/some/skill")
        tsc.write_source_record(self.tmp, skill, "4.0.0")
        record = tsc.read_source_record(self.tmp)
        # 断言的是"原样往返"，不绑定分隔符：Windows 上 str(Path("/some/skill")) 为 \some\skill
        self.assertEqual(record["source"], str(skill))
        self.assertEqual(record["version"], "4.0.0")
        self.assertIn("installed_at", record)
        self.assertTrue(tsc.source_record_current(self.tmp, skill, "4.0.0"))
        self.assertFalse(tsc.source_record_current(self.tmp, Path("/other"), "4.0.0"))

    def test_legacy_plain_path_record_reads_but_never_current(self):
        (self.tmp / ".agents" / ".source").write_text("/old/skill\n", encoding="utf-8")
        record = tsc.read_source_record(self.tmp)
        self.assertEqual(record["source"], "/old/skill")
        self.assertTrue(record.get("legacy"))
        self.assertFalse(tsc.source_record_current(self.tmp, Path("/old/skill"), "3.3.2"))

    def test_missing_or_corrupt_record(self):
        self.assertIsNone(tsc.read_source_record(self.tmp))
        # 损坏/非 JSON 内容按旧版纯文本兼容读取（只是记录，永不参与选源，无害）
        (self.tmp / ".agents" / ".source").write_text("{broken", encoding="utf-8")
        record = tsc.read_source_record(self.tmp)
        self.assertEqual(record["source"], "{broken")
        self.assertTrue(record.get("legacy"))


class NodeDetectionTests(unittest.TestCase):
    """P1-04：只有 Node/JS 项目才部署 commitlint。"""

    def setUp(self):
        import shutil
        self.tmp = Path(tempfile.mkdtemp(prefix="tsc-node-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_python_only_project_is_not_node(self):
        self.assertFalse(tsc.is_node_project(self.tmp))

    def test_package_json_makes_node(self):
        (self.tmp / "package.json").write_text("{}", encoding="utf-8")
        self.assertTrue(tsc.is_node_project(self.tmp))

    def test_strip_node_regions_removes_block(self):
        text = "a\n# tsc:begin:node-only\nnpm-thing\n# tsc:end:node-only\nb\n"
        self.assertEqual(tsc.strip_node_regions(text), "a\nb\n")

    def test_strip_node_regions_keeps_other_comments(self):
        text = "# tsc-managed —— 托管说明\nkeep\n"
        self.assertEqual(tsc.strip_node_regions(text), text)

    def test_template_precommit_has_node_region(self):
        text = tsc.read_text(SKILL / "templates/enforcement/.pre-commit-config.yaml")
        self.assertIn(tsc.NODE_REGION_BEGIN, text)
        self.assertIn(tsc.NODE_REGION_END, text)
        self.assertIn("@commitlint/cli", text)  # node 区块里才有 commitlint
        stripped = tsc.strip_node_regions(text)
        self.assertNotIn("@commitlint/cli", stripped)
        self.assertIn("gitleaks", stripped)      # 密钥扫描保留
        self.assertIn("structure_guard", stripped)  # 结构门禁保留


class EnforceActionsTests(unittest.TestCase):
    """执法包归属三态：直接调 _enforce_actions（判定单源）。"""

    def setUp(self):
        import shutil
        self.tmp = Path(tempfile.mkdtemp(prefix="tsc-act-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def actions(self, agents_text=AGENTS_SAMPLE):
        return tsc._enforce_actions(self.tmp, SKILL, agents_text)

    def test_fresh_deploy_python_project(self):
        # 非 Node 项目：4 份（gate.yml / pre-commit / structure_guard / bracket_lint），无 commitlint
        deploy, update, skip = self.actions()
        self.assertEqual(sorted(n for n, _ in deploy), sorted([
            ".github/workflows/gate.yml",
            ".pre-commit-config.yaml",
            ".agents/structure_guard.py",
            ".agents/bracket_lint.py",
        ]))
        self.assertEqual((update, skip), ([], []))

    def test_fresh_deploy_node_project_adds_commitlint(self):
        (self.tmp / "package.json").write_text("{}", encoding="utf-8")
        deploy, _, _ = self.actions()
        self.assertIn("commitlint.config.js", [n for n, _ in deploy])

    def test_structure_guard_lands_with_managed_marker(self):
        tsc.deploy_enforcement(self.tmp, SKILL, AGENTS_SAMPLE, dry_run=False)
        for rel in (".agents/structure_guard.py", ".agents/bracket_lint.py"):
            self.assertIn(tsc.MANAGED_MARKER, tsc.read_text(self.tmp / rel), rel)

    def test_python_project_precommit_has_no_npx(self):
        tsc.deploy_enforcement(self.tmp, SKILL, AGENTS_SAMPLE, dry_run=False)
        text = tsc.read_text(self.tmp / ".pre-commit-config.yaml")
        self.assertNotIn("npx", text)
        self.assertNotIn("@commitlint", text)
        self.assertIn("gitleaks", text)

    def test_deployed_precommit_guard_entry_uses_resolvable_interpreter(self):
        """A-05：落盘件里的解释器名必须在本机解析得到，否则闸 2 开箱就坏。

        模板给的是默认值，真正可用的名字由 `install / sync` 按本机探测后填入——
        所以这里断言的不是某个具体名字，而是「解析得到」这个不变量
        （Windows 上是 python，macOS/Linux 上是 python3，都对）。
        """
        import shutil
        if tsc.pick_precommit_interpreter() is None:
            self.skipTest("本机既无 python3 也无 python，无法验证探测结果")
        tsc.deploy_enforcement(self.tmp, SKILL, AGENTS_SAMPLE, dry_run=False)
        content = tsc.read_text(self.tmp / ".pre-commit-config.yaml")
        entries = [ln.strip() for ln in content.splitlines()
                   if ln.strip().startswith("entry:")]
        self.assertTrue(entries)
        for ln in entries:
            token = ln.split(":", 1)[1].strip().split()[0]
            self.assertTrue(shutil.which(token), "落盘件首令牌本机解析不到：%s" % ln)

    def test_node_project_precommit_keeps_npx(self):
        (self.tmp / "package.json").write_text("{}", encoding="utf-8")
        tsc.deploy_enforcement(self.tmp, SKILL, AGENTS_SAMPLE, dry_run=False)
        text = tsc.read_text(self.tmp / ".pre-commit-config.yaml")
        self.assertIn("npx", text)

    def test_managed_same_content_is_noop(self):
        tsc.deploy_enforcement(self.tmp, SKILL, AGENTS_SAMPLE, dry_run=False)
        deploy, update, skip = self.actions()
        self.assertEqual((deploy, update, skip), ([], [], []))

    def test_managed_drift_gets_update(self):
        tsc.deploy_enforcement(self.tmp, SKILL, AGENTS_SAMPLE, dry_run=False)
        # 项目后来才变成 Node 项目：sync 应补部署 commitlint
        (self.tmp / "package.json").write_text("{}", encoding="utf-8")
        deploy, update, skip = self.actions()
        self.assertIn("commitlint.config.js", [n for n, _ in deploy])
        self.assertEqual(skip, [])

    def test_user_takeover_is_skipped(self):
        tsc.deploy_enforcement(self.tmp, SKILL, AGENTS_SAMPLE, dry_run=False)
        target = self.tmp / ".pre-commit-config.yaml"
        lines = [ln for ln in tsc.read_text(target).splitlines() if tsc.MANAGED_MARKER not in ln]
        lines.append("# 项目自己改过的钩子配置")
        tsc.write_text_atomic(target, "\n".join(lines) + "\n")
        deploy, update, skip = self.actions()
        self.assertEqual((deploy, update), ([], []))
        self.assertEqual([(n, why) for n, why in skip],
                         [(".pre-commit-config.yaml", "内容已被项目改过")])

    def test_takeover_edit_on_mention_line_is_respected(self):
        """接管后改动"正文里含 tsc-managed 的说明行"也必须算项目已改过。

        旧实现把"含该子串的行"一律当标记行丢弃，导致这类改动在正文比对里隐形
        → 被误判成"旧版未改动的文件"而升级覆盖。
        """
        tsc.deploy_enforcement(self.tmp, SKILL, AGENTS_SAMPLE, dry_run=False)
        target = self.tmp / ".github" / "workflows" / "gate.yml"
        lines = [ln for ln in tsc.read_text(target).splitlines()
                 if not tsc.is_marker_line(ln, tsc.MANAGED_MARKER)]
        # 项目接管：删掉标记行，并把残留说明行改成自己的口径（该行仍含 tsc-managed 字样）
        lines = [ln.replace("# 检查器是 tsc-managed 落盘件",
                            "# 检查器是 tsc-managed 落盘件，本项目已自建替代")
                 for ln in lines]
        tsc.write_text_atomic(target, "\n".join(lines) + "\n")
        self.assertIn(tsc.MANAGED_MARKER, tsc.read_text(target))  # 前置：提及仍在
        deploy, update, skip = self.actions()
        self.assertEqual((deploy, [n for n, _ in update]), ([], []))
        self.assertEqual([n for n, _ in skip], [".github/workflows/gate.yml"])

    def test_gate_yml_branch_follows_section2(self):
        tsc.deploy_enforcement(self.tmp, SKILL, AGENTS_SAMPLE, dry_run=False)
        gate = tsc.read_text(self.tmp / ".github" / "workflows" / "gate.yml")
        self.assertIn("branches: [master]", gate)
        self.assertNotIn("branches: [main]", gate)

    def test_gate_yml_keeps_default_branch_when_trunk_is_none(self):
        sample = AGENTS_SAMPLE.replace("| 主干分支 | master |", "| 主干分支 | 无 |")
        tsc.deploy_enforcement(self.tmp, SKILL, sample, dry_run=False)
        gate = tsc.read_text(self.tmp / ".github" / "workflows" / "gate.yml")
        self.assertIn("branches: [main]", gate)
        self.assertNotIn("branches: [无", gate)

    def test_self_target_skips_enforcement(self):
        """母版自举不铺执法包——技能目录是仓库子目录的新布局也算自举。"""
        self.assertEqual(tsc._enforce_actions(SKILL, SKILL, AGENTS_SAMPLE), ([], [], []))
        # 本轮改造引入过的回归：技能搬到子目录后，"仓库根 vs 上游"不再相等，
        # 若判据不跟着改，母版会把自己当成待接入项目、把执法包铺进仓库根。
        self.assertEqual(tsc._enforce_actions(REPO, SKILL, AGENTS_SAMPLE), ([], [], []))


class GateTimeoutTests(unittest.TestCase):
    """P1-05：门禁命令超时必须终止进程组并返回 124。

    夹具用当前解释器而不是 `true` / `sleep`——那两个是 POSIX 专属，Windows 上
    根本没有，会让"快速直通"与"超时击杀"两组用例在 Windows 上必然失败（A-02）。
    """

    def test_fast_command_passes_through(self):
        code, timed_out = tsc.run_gate_command(QUICK_CMD, Path("."), 10)
        self.assertEqual((code, timed_out), (0, False))

    def test_nonzero_exit_passthrough(self):
        code, timed_out = tsc.run_gate_command("exit 7", Path("."), 10)
        self.assertEqual((code, timed_out), (7, False))

    def test_sleeping_command_is_killed_with_124(self):
        import time
        start = time.monotonic()
        code, timed_out = tsc.run_gate_command(SLOW_CMD, Path("."), 1)
        elapsed = time.monotonic() - start
        self.assertTrue(timed_out)
        self.assertEqual(code, tsc.EXIT_TIMEOUT)
        self.assertLess(elapsed, 10, "超时后必须立即杀掉，不能等它自己睡完")

    def test_default_timeout_constant(self):
        self.assertEqual(tsc.DEFAULT_TIMEOUT_S, 600)
        self.assertEqual(tsc.EXIT_TIMEOUT, 124)


class InterpreterRetargetTests(unittest.TestCase):
    """A-01：命令源里的解释器名各平台不齐，执行前必须能兜住。

    AGENTS.md §2 与 .agents/project.py 要求两处写**同一个静态字符串**才能做同源校验，
    所以写不出 sys.executable；而 Windows 常见只有 python、部分 Linux/macOS 只有
    python3。写死任何一个都会在另一平台上"命令找不到"，让门禁在最需要它的时候崩掉。
    修复后：解析得到就原样执行，解析不到才换成当前解释器，并明确告警。
    """

    def test_missing_interpreter_falls_back_to_current(self):
        cmd, changed = tsc.retarget_interpreter("python3.99 -m unittest")
        self.assertTrue(changed)
        self.assertIn(sys.executable, cmd)
        self.assertTrue(cmd.endswith("-m unittest"))

    def test_quoted_missing_interpreter_falls_back(self):
        cmd, changed = tsc.retarget_interpreter('"python9" -c "pass"')
        self.assertTrue(changed)
        self.assertEqual(cmd, '"%s" -c "pass"' % sys.executable)

    def test_resolvable_interpreter_is_left_alone(self):
        cmd = '"%s" -m unittest' % sys.executable
        self.assertEqual(tsc.retarget_interpreter(cmd), (cmd, False))

    def test_non_interpreter_command_is_left_alone(self):
        for cmd in ("echo hi", "node build.js", "pytest -q", ""):
            self.assertEqual(tsc.retarget_interpreter(cmd), (cmd, False),
                             "不该动这条命令：%r" % cmd)

    def test_retargeted_command_really_runs(self):
        code, timed_out = tsc.run_gate_command("python3.99 -c pass", Path("."), 10)
        self.assertEqual((code, timed_out), (0, False))


class SelfBootstrapTests(unittest.TestCase):
    """A-03：判"目标就是上游本体的宿主仓库"的口径必须只有一处，否则自检必然说谎。

    技能目录搬家到 `<仓库根>/skills/tsc/` 之后，判据不能再是"项目根 == 上游"
    （那样母版仓库自己反而不算自举，sync 会把执法包铺进仓库根）。
    """

    def test_master_repo_with_skill_subdir_is_self_bootstrap(self):
        self.assertTrue(tsc.is_self_bootstrap(REPO, SKILL))

    def test_legacy_root_layout_is_still_self_bootstrap(self):
        self.assertTrue(tsc.is_self_bootstrap(REPO, REPO))
        self.assertTrue(tsc.is_self_bootstrap(REPO / ".", REPO))

    def test_subdir_is_not_self_bootstrap(self):
        self.assertFalse(tsc.is_self_bootstrap(REPO / "tests", REPO))

    def test_consumer_project_is_not_self_bootstrap(self):
        """宿主把技能装进项目内的 .claude/skills/ 时，那是待接入项目，必须照常部署。"""
        import shutil
        proj = Path(tempfile.mkdtemp(prefix="tsc-cons-"))
        self.addCleanup(shutil.rmtree, proj, True)
        vendored = proj / ".claude" / "skills" / "tsc"
        vendored.mkdir(parents=True)
        self.assertFalse(tsc.is_self_bootstrap(proj, vendored))

    def test_none_upstream_is_not_self_bootstrap(self):
        self.assertFalse(tsc.is_self_bootstrap(REPO, None))


class GitWorktreeTests(unittest.TestCase):
    """`git_worktree_of`：技能目录自身是 git 副本、或是某仓库的子目录，都要认出来。

    只看 `<技能根>/.git` 会把母版布局误判成"非 git 安装"，进而谎报
    `tsc update` 不可用、doctor 的"本体更新通道"常年报错。
    """

    def test_master_layout_finds_repo_root(self):
        """技能目录是仓库子目录时，worktree 解析要落回仓库根。

        用临时布局断言——干净 clone / 无 .git 的副本环境同样成立（verify 在
        干净仓库必须稳定退出 0，不能依赖本机仓库恰好带着 .git）。"""
        import shutil
        tmp = Path(tempfile.mkdtemp(prefix="tsc-wt-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / ".git").mkdir()
        skill = tmp / "skills" / "tsc"
        skill.mkdir(parents=True)
        self.assertEqual(tsc.git_worktree_of(skill), tmp)
        if (REPO / ".git").exists():  # 真实仓库是 git 安装时一并校验
            self.assertEqual(tsc.git_worktree_of(SKILL), REPO)

    def test_plain_dir_has_no_worktree(self):
        import shutil
        tmp = Path(tempfile.mkdtemp(prefix="tsc-nogit-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        self.assertIsNone(tsc.git_worktree_of(tmp))


class SkillPackagingTests(unittest.TestCase):
    """技能打包不变量：自包含 + 平台中立。

    历史：v4.0.0 曾把本仓库做成单一平台的插件（平台清单 + hook 清单 + 市场目录），
    那套外壳只能被那一个平台安装，与"通用技能"的目标相反，已移除。这里锁死两条：
    技能目录必须自包含（拷这一个目录到任何平台的技能目录就能跑），
    且全仓不得再出现任何平台私有清单与占位符。
    """

    REQUIRED = (
        "SKILL.md",
        "VERSION",
        "scripts/tsc.py",
        "scripts/structure_guard.py",
        "scripts/bracket_lint.py",
        "scripts/install_hook.py",
        "templates/AGENTS.md",
        "templates/project.example.py",
        "templates/enforcement/gate.yml",
        "templates/enforcement/.pre-commit-config.yaml",
        "templates/enforcement/commitlint.config.js",
        "templates/enforcement/README.md",
        "references/AUDIT-SPEC.md",
        "references/BOOTSTRAP.md",
    )

    def test_skill_dir_is_self_contained(self):
        """运行期所需的一切都在技能目录内，不依赖仓库其它部分。"""
        for rel in self.REQUIRED:
            self.assertTrue((SKILL / rel).is_file(), "技能目录缺 %s" % rel)

    def test_upstream_root_is_skill_dir(self):
        # tsc.py 以"脚本的上一级"定位上游：那一级必须是技能根，否则 templates/ 找不到
        self.assertEqual(tsc.upstream_root(), SKILL)
        self.assertEqual(tsc.validate_upstream(tsc.upstream_root()), [])

    def test_no_platform_private_packaging_left(self):
        # 平台名同样拆开拼：本测试文件自己也在扫描范围内，字面量会把测试扫成违规
        platform = "zc" + "ode"
        for rel in ("." + platform + "-plugin", "marketplace.json", "hooks", "hooks/hooks.json"):
            self.assertFalse((REPO / rel).exists(), "残留平台私有件：%s" % rel)

    def test_no_platform_private_tokens_anywhere(self):
        """全仓不得再出现平台专属变量/清单名；CHANGELOG 是历史记录，按规则不改不扫。

        断言用的字面量刻意拆开拼接——否则本测试会把自己扫成违规
        （与"提及 ≠ 声明"同一类坑）。
        """
        token = "zc" + "ode"
        marker = "${" + "zc" + "ode_plugin_root}"
        files = [REPO / "README.md", REPO / "AGENTS.md"]
        for base in (SKILL, REPO / "tests", REPO / ".github"):
            files.extend(p for p in sorted(base.rglob("*")) if p.is_file())
        for path in files:
            if "__pycache__" in path.parts:
                continue
            if path.suffix not in (".py", ".md", ".yml", ".yaml", ".json", ".js"):
                continue
            text = tsc.read_text(path).lower()
            self.assertNotIn(token, text, path.as_posix())
            self.assertNotIn(marker, text, path.as_posix())

    def test_skill_frontmatter_has_only_standard_fields(self):
        text = tsc.read_text(SKILL / "SKILL.md")
        self.assertTrue(text.startswith("---\n"))
        front = text.split("---\n")[1]
        self.assertRegex(front, r"(?m)^name: tsc\s*$")
        self.assertIn("description:", front)
        # P2-01：非标准字段收进 metadata，顶层不许再挂 version/display_name 等
        self.assertIsNone(re.search(r"(?m)^version:", front))
        self.assertIsNone(re.search(r"(?m)^display_name:", front))
        self.assertIn("metadata:", front)

    def test_commands_exist(self):
        for name in ("tsc.md", "tsc-update.md", "tsc-status.md", "tsc-sync.md"):
            self.assertTrue((SKILL / "commands" / name).is_file(), name)
        update_cmd = tsc.read_text(SKILL / "commands/tsc-update.md")
        sync_cmd = tsc.read_text(SKILL / "commands/tsc-sync.md")
        # P2-07：本体升级与项目同步是两个入口，互不越界
        self.assertIn("不要", update_cmd + sync_cmd)

    def test_commands_paths_valid(self):
        # B-04：commands 中的引用路径应使用 <技能根> 或相对于技能根的有效路径
        tsc_cmd = tsc.read_text(SKILL / "commands/tsc.md")
        self.assertNotIn("skills/tsc/references", tsc_cmd)
        self.assertIn("<技能根>/references/AUDIT-SPEC.md", tsc_cmd)


    def test_no_hardcoded_proxy_anywhere_user_facing(self):
        # P2-02：公共仓库绝不绑定作者本机代理端口
        for rel in ("README.md", "skills/tsc/SKILL.md",
                    "skills/tsc/commands/tsc.md",
                    "skills/tsc/commands/tsc-update.md",
                    "skills/tsc/commands/tsc-sync.md"):
            self.assertNotIn("127.0.0.1:7897", tsc.read_text(REPO / rel), rel)

    def test_version_single_source(self):
        # P2-10 + 收官体检 A-07：版本真源是技能 VERSION；所有头注动态比对，不硬编码
        # （下次发版不红），且模板/实例 AGENTS.md 的版本头注漂移在 CI 里也能抓到
        ver = (SKILL / "VERSION").read_text(encoding="utf-8").strip()
        self.assertRegex(ver, r"^\d+\.\d+\.\d+$")
        local = REPO / ".agents" / "VERSION"  # 本机自举生成、被 gitignore；存在则必须一致
        if local.exists():
            self.assertEqual(tsc.read_text(local).strip(), ver)
        for rel in ("skills/tsc/templates/AGENTS.md", "AGENTS.md"):
            m = re.search(r"版本 v(\d+\.\d+\.\d+)", tsc.read_text(REPO / rel))
            self.assertIsNotNone(m, "%s 缺版本头注" % rel)
            self.assertEqual(m.group(1), ver, "%s 版本头注与 VERSION 漂移" % rel)
        self.assertEqual(tsc.upstream_version(SKILL), ver)

    def test_contract_line_budget(self):
        """契约行数预算：母版与实例都必须 < 80 行（`wc -l` LF 口径）。

        A-09 的教训：只剩 1 行余量时，任何一条新规则都会直接撞门禁。把它变成自动
        断言，比发版清单里手敲一次 `wc -l` 靠谱——手敲的到不了 CI。
        """
        for rel in ("AGENTS.md", "skills/tsc/templates/AGENTS.md"):
            lines = tsc.read_text(REPO / rel).count("\n")
            self.assertLess(lines, 80, "%s 已 %d 行，超出 80 行预算" % (rel, lines))

    def test_contract_rule_budget(self):
        """行数头注里同时声明了"≤30 条规则"，一并锁住，防止只盯行数。"""
        text = tsc.read_text(SKILL / "templates/AGENTS.md")
        rules = sorted(set(re.findall(r"\bR-\d+\.\d+\b", text)))
        self.assertLessEqual(len(rules), 30, "规则数 %d 超预算：%s" % (len(rules), rules))
        self.assertGreaterEqual(len(rules), 15, "规则数异常偏少，可能编号被改坏：%s" % rules)


class EnforcementTemplateTests(unittest.TestCase):
    """执法包模板自身的静态约束（供应链 / Node 条件）。"""

    def test_gate_yml_pins_actions_and_dependencies(self):
        gate = tsc.read_text(SKILL / "templates/enforcement/gate.yml")
        uses_lines = [
            ln.strip() for ln in gate.splitlines()
            if "uses:" in ln and not ln.strip().startswith("#")
        ]
        self.assertTrue(uses_lines)
        for ln in uses_lines:
            self.assertNotRegex(ln, r"uses: \S+@v\d+", "浮动 tag：%s" % ln)
            self.assertRegex(ln, r"[0-9a-f]{40}", "未钉 SHA：%s" % ln)
        self.assertIn("@commitlint/cli@21.2.2", gate)

    def test_ci_workflow_is_multiplatform_and_shipped_unmanaged(self):
        """母版自身的 CI：三平台矩阵 + 供应链钉 SHA（与 gate.yml 同一套标准）。

        它刻意不叫 gate.yml、也不带 tsc-managed 标记——母版不部署自己的执法包，
        这条工作流是维护者手工维护的独立回归线。
        """
        text = tsc.read_text(REPO / ".github/workflows/ci.yml")
        for os_name in ("ubuntu-latest", "windows-latest", "macos-latest"):
            self.assertIn(os_name, text)
        uses_lines = [ln.strip() for ln in text.splitlines()
                      if "uses:" in ln and not ln.strip().startswith("#")]
        self.assertTrue(uses_lines)
        for ln in uses_lines:
            self.assertNotRegex(ln, r"uses: \S+@v\d+", "浮动 tag：%s" % ln)
            self.assertRegex(ln, r"[0-9a-f]{40}", "未钉 SHA：%s" % ln)
        self.assertIn("tsc.py verify", text)
        # 用 is_marker_line 的真语义判"声明"，不做子串匹配——本文件注释里**提到**了
        # 托管标记，子串判断会把说明误判成声明（与"提及 ≠ 声明"同一类坑）。
        self.assertFalse(tsc.has_marker(text, tsc.MANAGED_MARKER), "母版 CI 不是托管落盘件")

    def test_gate_yml_commitlint_condition_only_uses_commitlint_file(self):
        # P1-04：Python-only 项目（没有 commitlint.config.js）绝不触发 npm 安装
        gate = tsc.read_text(SKILL / "templates/enforcement/gate.yml")
        self.assertIn("hashFiles('commitlint.config.js') != ''", gate)
        for ln in gate.splitlines():
            if "hashFiles(" in ln and "npm" not in ln:
                self.assertNotIn(".pre-commit-config.yaml", ln,
                                 "commitlint 条件不得再认 pre-commit 配置（会让 Python 项目被迫装 npm）")

    def test_precommit_pins_gitleaks_to_sha(self):
        # P2-06：pre-commit 远程仓钉 40 位 commit SHA，保留 tag 注释
        text = tsc.read_text(SKILL / "templates/enforcement/.pre-commit-config.yaml")
        for ln in text.splitlines():
            if ln.strip().startswith("rev:"):
                self.assertRegex(ln, r"rev: [0-9a-f]{40}", ln)
        self.assertIn("# v8.30.1", text)

    def test_precommit_template_uses_system_language(self):
        """A-05 的最终结论：pre-commit 的 local 钩子只能用 `language: system`。

        另两条路都实测排除了（2026-09-23 对照实验）：
        - `language: python`：pre-commit 会先对项目根执行 `pip install .`，没有
          setup.py / pyproject.toml 的项目直接
          `ERROR: Directory '.' is not installable` —— 所有平台一起坏；
        - `language: script` + 项目内 sh 启动器：Windows 上报
          `Executable '/bin/sh' not found`。

        而 system 语言的 entry 首令牌**完全靠系统 PATH 解析**，python3 / python
        各平台不齐，静态写死哪个都只在半边平台成立 → 名字改由部署时探测填入
        （见 `pick_precommit_interpreter`）。
        """
        text = tsc.read_text(SKILL / "templates/enforcement/.pre-commit-config.yaml")
        # 只看**生效指令行**：注释里会解释"为什么不用 language: python"，
        # 子串判断会把说明误判成声明（"提及 ≠ 声明"那个坑的又一次实例）。
        # 注意 commitlint 条目也是 system（两个钩子都用 system 才正常）。
        active = [ln.strip() for ln in text.splitlines()
                  if ln.strip().startswith("language:")]
        self.assertTrue(active, "模板里应有 language: 指令行")
        self.assertEqual(set(active), {"language: system"}, active)
        self.assertIn("structure_guard", text)
        self.assertIn(tsc.PRE_COMMIT_GUARD_ENTRY, text, "模板应保留默认 entry")

    def test_enforcement_templates_carry_managed_marker(self):
        for rel in ("skills/tsc/templates/enforcement/gate.yml",
                    "skills/tsc/templates/enforcement/.pre-commit-config.yaml",
                    "skills/tsc/templates/enforcement/commitlint.config.js"):
            self.assertIn(tsc.MANAGED_MARKER, tsc.read_text(REPO / rel), rel)


class LegacyStructureTests(unittest.TestCase):
    def test_detect_legacy_needs_contract_evidence(self):
        import shutil
        tmp = Path(tempfile.mkdtemp(prefix="tsc-leg-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        # 无 AGENTS.md：根 test/ 是项目自己的
        (tmp / "test").mkdir()
        (tmp / "test" / "test_user_own.py").write_text("print('own')\n", encoding="utf-8")
        self.assertEqual(tsc.detect_legacy(tmp), [])
        # ≥2 个契约签名才认
        (tmp / "AGENTS.md").write_text(AGENTS_SAMPLE, encoding="utf-8")
        (tmp / "test" / "EVAL-SET.md").write_text("x\n", encoding="utf-8")
        (tmp / "test" / "TEST-MANUAL.md").write_text("x\n", encoding="utf-8")
        self.assertEqual(tsc.detect_legacy(tmp), ["test"])

    def test_skill_only_leftovers_self_scan_is_empty(self):
        self.assertEqual(tsc.detect_skill_only_leftovers(REPO), [])


class AtomicWriteTests(unittest.TestCase):
    def test_atomic_write_cleans_tmp_on_failure(self):
        import shutil
        from unittest import mock
        target_dir = Path(tempfile.mkdtemp(prefix="tsc-tmp-"))
        self.addCleanup(shutil.rmtree, target_dir, True)
        target = target_dir / "f.txt"
        with mock.patch("os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                tsc.write_text_atomic(target, "x")
        self.assertEqual(list(target_dir.glob("*.tsc-tmp")), [])


class DispatchTests(unittest.TestCase):
    def test_nonexistent_project_fails_early(self):
        rc = tsc.main(["verify", "--project", "non_existent_folder_xyz_123"])
        self.assertEqual(rc, tsc.EXIT_STATE)

    def test_status_nonexistent_project_fails_early(self):
        rc = tsc.main(["status", "--project", "non_existent_folder_xyz_123"])
        self.assertEqual(rc, tsc.EXIT_STATE)


class TemplateSanitizationTests(unittest.TestCase):
    def test_main_branch_sanitization_in_enforce_template(self):
        agents_sample_trunk = AGENTS_SAMPLE.replace("| 主干分支 | master |", "| 主干分支 | `trunk` |")
        out = tsc.enforce_template_content("templates/enforcement/gate.yml", REPO, SKILL, agents_sample_trunk)
        self.assertIsNotNone(out)
        self.assertIn("branches: [trunk]", out)


class InterpreterHeadRegexTests(unittest.TestCase):
    """_INTERPRETER_HEAD 正则本身的匹配口径（与 InterpreterRetargetTests 分开——
    曾因同名类把前一个类整个遮蔽，5 条回退测试从未运行，收官体检 A-05）。"""

    def test_retarget_matches_exe_and_case(self):
        m = tsc._INTERPRETER_HEAD.match("python.exe -m pytest")
        self.assertIsNotNone(m)
        self.assertEqual(m.group("token"), "python.exe")
        m2 = tsc._INTERPRETER_HEAD.match("Py.exe -3")
        self.assertIsNotNone(m2)


class RollbackParentDirTests(unittest.TestCase):
    def test_rollback_recreates_deleted_parent_dir(self):
        import shutil
        tmp = Path(tempfile.mkdtemp(prefix="tsc-rb-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        backup_dir = tmp / tsc.AGENTS_DIR / tsc.BACKUP_DIRNAME
        backup_dir.mkdir(parents=True)
        manifest_file = backup_dir / "manifest.json"
        manifest_data = {
            "contract_version": "5.0.0",
            "files": [
                {
                    "path": "sub/target.txt",
                    "action": "modify",
                    "content": "restored",
                }
            ]
        }
        manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")
        target_file = tmp / "sub" / "target.txt"
        self.assertFalse((tmp / "sub").exists())
        rc = tsc.cmd_rollback(tmp)
        self.assertEqual(rc, 0)
        self.assertTrue(target_file.is_file())
        self.assertEqual(target_file.read_text(encoding="utf-8"), "restored")


class RowToKeyEnglishTests(unittest.TestCase):
    def test_row_to_key_english_headers(self):
        import shutil
        tmp = Path(tempfile.mkdtemp(prefix="tsc-row-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        agents_content = """# Title
## 2. Project
| Key | Command | Status |
|---|---|---|
| Format | black --check | ok |
| Lint | ruff check | ok |
| Test | pytest | ok |
| Build | cargo build | ok |
## 3. End
"""
        (tmp / tsc.AGENTS_MD).write_text(agents_content, encoding="utf-8")
        table = tsc.read_section2_values(tmp)
        self.assertIsNotNone(table)
        self.assertEqual(table.get("FMT_CHECK_CMD"), "black --check")
        self.assertEqual(table.get("LINT_CMD"), "ruff check")
        self.assertEqual(table.get("TEST_CMD"), "pytest")
        self.assertEqual(table.get("BUILD_CMD"), "cargo build")


class SafeProjectPathTests(unittest.TestCase):
    """路径安全唯一入口：拒绝绝对路径、`..`、symlink/junction 逃逸。"""

    def setUp(self):
        import shutil
        self.tmp = Path(tempfile.mkdtemp(prefix="tsc-safe-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_plain_relative_path_ok(self):
        for rel in (".agents/VERSION", "AGENTS.md", ".github/workflows/gate.yml",
                    "a/b/c.txt"):
            target, resolved = tsc.safe_project_path(self.tmp, rel)
            self.assertTrue(str(resolved).startswith(str(self.tmp.resolve())))

    def test_absolute_paths_rejected(self):
        for rel in ("/etc/passwd", "C:/Windows/system32", "C:\\Windows\\system32"):
            with self.assertRaises(tsc.UnsafeProjectPath):
                tsc.safe_project_path(self.tmp, rel)

    def test_dotdot_rejected(self):
        for rel in ("../escape", "a/../../escape", "..\\escape", "a/..", ".."):
            with self.assertRaises(tsc.UnsafeProjectPath):
                tsc.safe_project_path(self.tmp, rel)

    def test_empty_rejected(self):
        for rel in ("", ".", "./"):
            with self.assertRaises(tsc.UnsafeProjectPath):
                tsc.safe_project_path(self.tmp, rel)

    def _make_link(self, link_dir, target_dir):
        """优先真 symlink；Windows 无特权时退回 junction；都不行返回 False。"""
        try:
            os.symlink(str(target_dir), str(link_dir), target_is_directory=True)
            return True
        except (OSError, NotImplementedError, AttributeError):
            pass
        try:
            import _winapi
            _winapi.CreateJunction(str(target_dir), str(link_dir))
            return True
        except (OSError, ImportError):
            return False

    def test_symlink_escape_rejected(self):
        import shutil
        outside = Path(tempfile.mkdtemp(prefix="tsc-out-"))
        self.addCleanup(shutil.rmtree, outside, True)
        (outside / "victim.txt").write_text("x", encoding="utf-8")
        link = self.tmp / ".agents"
        if not self._make_link(link, outside):
            self.skipTest("本机既不能建 symlink 也不能建 junction，跳过")
        with self.assertRaises(tsc.UnsafeProjectPath):
            tsc.safe_project_path(self.tmp, ".agents/VERSION")
        # 受管理路径逐层检查：深层路径也会在 .agents 这一层被拦
        with self.assertRaises(tsc.UnsafeProjectPath):
            tsc.safe_project_path(self.tmp, ".agents/sub/deep.txt")

    def test_symlink_inside_root_also_rejected(self):
        """指向项目内部其它目录的 symlink 同样拒绝——受管理路径不允许被重定向。"""
        inside = self.tmp / "elsewhere"
        inside.mkdir()
        link = self.tmp / ".github"
        if not self._make_link(link, inside):
            self.skipTest("本机既不能建 symlink 也不能建 junction，跳过")
        with self.assertRaises(tsc.UnsafeProjectPath):
            tsc.safe_project_path(self.tmp, ".github/workflows/gate.yml")


class ProjectConfigAstTests(unittest.TestCase):
    """project.py 只允许 AST 白名单常量解析，绝不 exec（配置文件不是可执行文件）。"""

    def setUp(self):
        import shutil
        self.tmp = Path(tempfile.mkdtemp(prefix="tsc-cfg-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def parse(self, text):
        p = self.tmp / "project.py"
        p.write_text(text, encoding="utf-8")
        return tsc.parse_project_config(p)

    def test_benign_config_parses(self):
        cfg, err = self.parse(
            '"""doc"""\n'
            '__all__ = ["TEST_CMD"]\n'
            'FMT_CHECK_CMD = None\nLINT_CMD = "ruff check ."\n'
            'TEST_CMD = "pytest -q"\nBUILD_CMD = None\n'
            'GATE_TIMEOUTS = {"TEST_CMD": 300}\n')
        self.assertIsNone(err)
        self.assertEqual(cfg["LINT_CMD"], "ruff check .")
        self.assertEqual(cfg["GATE_TIMEOUTS"], {"TEST_CMD": 300})

    def test_malicious_import_never_runs(self):
        marker = self.tmp / "pwned.txt"
        cfg, err = self.parse(
            'import os\n'
            'os.system("echo pwned > %s")\n'
            'TEST_CMD = "x"\n' % marker.as_posix())
        self.assertIsNone(cfg)
        self.assertIn("import", err)
        self.assertFalse(marker.exists(), "AST 解析路径绝不能执行任何代码")

    def test_malicious_call_rejected(self):
        cfg, err = self.parse('TEST_CMD = __import__("os").getcwd()\n')
        self.assertIsNone(cfg)
        self.assertIn("禁止函数调用", err)

    def test_malicious_attribute_rejected(self):
        cfg, err = self.parse('import sys\nTEST_CMD = sys.executable\n')
        self.assertIsNone(cfg)

    def test_malicious_print_rejected(self):
        cfg, err = self.parse('print("hello")\nTEST_CMD = "x"\n')
        self.assertIsNone(cfg)

    def test_function_def_rejected(self):
        cfg, err = self.parse('def run():\n    pass\nTEST_CMD = "x"\n')
        self.assertIsNone(cfg)

    def test_name_reference_rejected(self):
        cfg, err = self.parse('BASE = "a"\nTEST_CMD = BASE + "b"\n')
        self.assertIsNone(cfg)

    def test_gate_timeouts_must_be_dict(self):
        cfg, err = self.parse('GATE_TIMEOUTS = "not-a-dict"\n')
        self.assertIsNone(cfg)
        self.assertIn("GATE_TIMEOUTS", err)

    def test_syntax_error_reported(self):
        cfg, err = self.parse('TEST_CMD = "unclosed\n')
        self.assertIsNone(cfg)
        self.assertIn("语法", err)


class BranchRenderingTests(unittest.TestCase):
    """gate.yml 的 branches 渲染必须 YAML-safe：特殊分支名绝不裸插值。"""

    def setUp(self):
        import shutil
        self.tmp = Path(tempfile.mkdtemp(prefix="tsc-br-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    SIMPLE = ("main", "master", "trunk", "develop", "release-1.2.3", "v1_x")

    def test_simple_branches_stay_bare(self):
        for name in self.SIMPLE:
            self.assertEqual(tsc.render_branches_entry(name), "branches: [%s]" % name)

    def test_special_branches_are_single_quoted(self):
        cases = {
            "release/1,2": "branches: ['release/1,2']",
            "fix]ing": "branches: ['fix]ing']",
            "main #not-comment": "branches: ['main #not-comment']",
            "a{b}c": "branches: ['a{b}c']",
            "sp ace": "branches: ['sp ace']",
            "quo'te": "branches: ['quo''te']",  # YAML 单引号内 ' 转义为 ''
            "a:b": "branches: ['a:b']",
        }
        for name, expected in cases.items():
            self.assertEqual(tsc.render_branches_entry(name), expected, name)

    def test_debranch_round_trips_every_variant(self):
        for name in list(self.SIMPLE) + ["release/1,2", "quo'te", "sp ace", "a{b}c"]:
            rendered = tsc.render_branches_entry(name)
            back = rendered
            for variant in tsc._branch_variants(name):
                back = back.replace(variant, "branches: [main]")
            self.assertEqual(back, "branches: [main]", name)

    def test_gate_yml_rendering_with_special_branch(self):
        agents = AGENTS_SAMPLE.replace("| 主干分支 | master |", "| 主干分支 | release/1,2 |")
        content = tsc.enforce_template_content(
            "templates/enforcement/gate.yml", self.tmp, SKILL, agents)
        self.assertIsNotNone(content)
        self.assertIn("branches: ['release/1,2']", content)
        self.assertNotIn("branches: [release/1,2]", content)  # 裸插值会产生坏 YAML


class CommitlintOptionalTests(unittest.TestCase):
    """commitlint 是可选适配层：项目已有提交规范配置时不部署。"""

    def setUp(self):
        import shutil
        self.tmp = Path(tempfile.mkdtemp(prefix="tsc-cl-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_non_node_never_wants_commitlint(self):
        wanted, _ = tsc.commitlint_wanted(self.tmp)
        self.assertFalse(wanted)

    def test_plain_node_project_wants(self):
        (self.tmp / "package.json").write_text('{"name": "x"}', encoding="utf-8")
        self.assertTrue(tsc.commitlint_wanted(self.tmp)[0])

    def test_existing_commitlint_config_blocks_deploy(self):
        (self.tmp / "package.json").write_text('{"name": "x"}', encoding="utf-8")
        (self.tmp / ".commitlintrc.json").write_text("{}", encoding="utf-8")
        wanted, reason = tsc.commitlint_wanted(self.tmp)
        self.assertFalse(wanted)
        self.assertIn(".commitlintrc", reason)
        deploy, update, skip = tsc._enforce_actions(self.tmp, SKILL, AGENTS_SAMPLE)
        self.assertNotIn("commitlint.config.js", [n for n, _ in deploy])

    def test_taken_over_commitlint_config_reports_takeover(self):
        """项目接管过的 commitlint.config.js：走执法包三态规则，显式跳过不覆盖。"""
        (self.tmp / "package.json").write_text('{"name": "x"}', encoding="utf-8")
        tsc.deploy_enforcement(self.tmp, SKILL, AGENTS_SAMPLE, dry_run=False)
        target = self.tmp / "commitlint.config.js"
        lines = [ln for ln in tsc.read_text(target).splitlines()
                 if not tsc.is_marker_line(ln, tsc.MANAGED_MARKER)]
        tsc.write_text_atomic(target, "\n".join(lines) + "\n// 项目接管\n")
        deploy, update, skip = tsc._enforce_actions(self.tmp, SKILL, AGENTS_SAMPLE)
        self.assertEqual((deploy, [n for n, _ in update]), ([], []))
        self.assertEqual([n for n, _ in skip], ["commitlint.config.js"])

    def test_lockfile_pm_detection(self):
        self.assertIsNone(tsc.detect_lockfile_pm(self.tmp))
        (self.tmp / "pnpm-lock.yaml").write_text("", encoding="utf-8")
        self.assertEqual(tsc.detect_lockfile_pm(self.tmp), "pnpm")


class UpstreamValidationTests(unittest.TestCase):
    """上游完整校验：必需产物清单 + 关键内容格式，残缺上游一票否决。"""

    def test_real_skill_passes(self):
        self.assertEqual(tsc.validate_upstream(SKILL), [])

    def test_missing_required_artifact_detected(self):
        import shutil
        broken = Path(tempfile.mkdtemp(prefix="tsc-up-"))
        self.addCleanup(shutil.rmtree, broken, True)
        shutil.copytree(SKILL, broken / "tsc", ignore=shutil.ignore_patterns("__pycache__"))
        (broken / "tsc" / "references" / "BOOTSTRAP.md").unlink()
        missing = tsc.validate_upstream(broken / "tsc")
        self.assertIn("references/BOOTSTRAP.md", missing)

    def test_bad_version_format_detected(self):
        import shutil
        broken = Path(tempfile.mkdtemp(prefix="tsc-up-"))
        self.addCleanup(shutil.rmtree, broken, True)
        shutil.copytree(SKILL, broken / "tsc", ignore=shutil.ignore_patterns("__pycache__"))
        (broken / "tsc" / "VERSION").write_text("not-a-version\n", encoding="utf-8")
        missing = tsc.validate_upstream(broken / "tsc")
        self.assertTrue(any("版本格式非法" in m for m in missing), missing)

    def test_template_without_marker_detected(self):
        import shutil
        broken = Path(tempfile.mkdtemp(prefix="tsc-up-"))
        self.addCleanup(shutil.rmtree, broken, True)
        shutil.copytree(SKILL, broken / "tsc", ignore=shutil.ignore_patterns("__pycache__"))
        tpl = broken / "tsc" / "templates" / "AGENTS.md"
        tpl.write_text(tsc.read_text(tpl).replace(tsc.CONTRACT_MARKER_LINE, ""), encoding="utf-8")
        missing = tsc.validate_upstream(broken / "tsc")
        self.assertTrue(any("所有权标记" in m for m in missing), missing)


class RollbackManifestValidationTests(unittest.TestCase):
    """rollback 在第一次写入之前完整校验 manifest：非法路径立即失败、零恢复。"""

    def setUp(self):
        import shutil
        self.tmp = Path(tempfile.mkdtemp(prefix="tsc-rbv-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.backup = self.tmp / ".agents" / ".tsc-backup"
        self.backup.mkdir(parents=True)
        (self.tmp / "AGENTS.md").write_text("current\n", encoding="utf-8")

    def write_manifest(self, files, moves=None):
        manifest = {"schema": 2, "contract_version": "5.2.0", "files": files,
                    "moves": moves or []}
        (self.backup / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    def assert_refused(self):
        rc = tsc.cmd_rollback(self.tmp)
        self.assertEqual(rc, tsc.EXIT_IO)
        # 关键不变量：拒绝恢复时项目文件一个都不动
        self.assertEqual((self.tmp / "AGENTS.md").read_text(encoding="utf-8"), "current\n")

    def test_traversal_path_refused(self):
        self.write_manifest([{"path": "../escape.txt", "action": "create"}])
        self.assert_refused()

    def test_absolute_path_refused(self):
        self.write_manifest([{"path": "C:/Windows/evil.txt", "action": "create"}])
        self.assert_refused()

    def test_nested_dotdot_refused(self):
        self.write_manifest([{"path": "a/../../evil.txt", "action": "modify", "content": "x"}])
        self.assert_refused()

    def test_move_traversal_refused(self):
        self.write_manifest([], moves=[{"from": "../steal", "to": ".agents/steal"}])
        self.assert_refused()

    def test_bad_action_refused(self):
        self.write_manifest([{"path": "AGENTS.md", "action": "delete"}])
        self.assert_refused()

    def test_missing_content_refused(self):
        self.write_manifest([{"path": "AGENTS.md", "action": "modify"}])
        self.assert_refused()

    def test_symlink_target_refused(self):
        import shutil as _shutil
        outside = Path(tempfile.mkdtemp(prefix="tsc-out2-"))
        self.addCleanup(_shutil.rmtree, outside, True)
        sub = self.tmp / "redirect"  # 链接挂载点：必须事先不存在
        made = False
        try:
            os.symlink(str(outside), str(sub), target_is_directory=True)
            made = True
        except (OSError, NotImplementedError, AttributeError):
            try:
                import _winapi
                _winapi.CreateJunction(str(outside), str(sub))
                made = True
            except (OSError, ImportError):
                pass
        if not made:
            self.skipTest("本机既不能建 symlink 也不能建 junction，跳过")
        self.write_manifest([{"path": "redirect/evil.txt", "action": "create"}])
        self.assert_refused()
        self.assertFalse((outside / "evil.txt").exists())

    def test_valid_manifest_with_move_restores(self):
        # 迁移记录能搬回：.agents/test → test
        (self.tmp / ".agents" / "test").mkdir(parents=True)
        (self.tmp / ".agents" / "test" / "EVAL-SET.md").write_text("x", encoding="utf-8")
        self.write_manifest([], moves=[{"from": "test", "to": ".agents/test"}])
        rc = tsc.cmd_rollback(self.tmp)
        self.assertEqual(rc, tsc.EXIT_OK)
        self.assertTrue((self.tmp / "test" / "EVAL-SET.md").is_file())
        self.assertFalse((self.tmp / ".agents" / "test").exists())


class TransactionUnitTests(unittest.TestCase):
    """事务单元行为：backup 失败先于任何项目写盘；写入失败自动恢复。"""

    def setUp(self):
        import shutil
        self.tmp = Path(tempfile.mkdtemp(prefix="tsc-txn-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_execute_transaction_backup_failure_leaves_project_untouched(self):
        # 备份目录被一个同名文件占用 → mkdir 失败 → 事务在任何项目写盘前终止
        (self.tmp / ".agents").mkdir()
        (self.tmp / ".agents" / ".tsc-backup").write_text("not a dir", encoding="utf-8")
        plan = {"writes": [("AGENTS.md", "hello\n", None)], "moves": []}
        code, problems, exc = tsc._execute_transaction(self.tmp, plan, "5.2.0")
        self.assertEqual(code, tsc.EXIT_IO)
        self.assertIsNotNone(exc)
        self.assertFalse((self.tmp / "AGENTS.md").exists(), "backup 失败不得写任何项目文件")
        self.assertFalse((self.tmp / ".agents" / ".tsc-backup" / "manifest.json").exists())

    def test_execute_transaction_write_failure_rolls_back(self):
        from unittest import mock
        plan = {
            "writes": [
                ("AGENTS.md", "new\n", "old\n"),
                (".github/workflows/gate.yml", "gate\n", None),
            ],
            "moves": [],
        }
        (self.tmp / "AGENTS.md").write_text("old\n", encoding="utf-8")
        calls = {"n": 0}
        real_write = tsc.write_text_atomic

        def flaky(path, text, dry_run=False):
            calls["n"] += 1
            if calls["n"] >= 2:  # 第二个写入（gate.yml）失败
                raise OSError("disk full")
            return real_write(path, text, dry_run)

        with mock.patch.object(tsc, "write_text_atomic", side_effect=flaky):
            code, problems, exc = tsc._execute_transaction(self.tmp, plan, "5.2.0")
        self.assertEqual(code, tsc.EXIT_IO)
        self.assertEqual((self.tmp / "AGENTS.md").read_text(encoding="utf-8"), "old\n")
        self.assertFalse((self.tmp / ".github").exists(), "新建目录必须一并回滚")
        backup_dir = self.tmp / ".agents" / ".tsc-backup"
        self.assertFalse((backup_dir / "manifest.json").exists(), "失败事务不得提交清单")
        self.assertFalse((backup_dir / "manifest.json.new").exists(), "失败事务不得留半成品")

    def test_migration_only_sync_gets_manifest(self):
        """migration-only 事务也必须有 committed 清单（moves 记录在案）。"""
        plan = {"writes": [], "moves": [("AUDIT-SPEC.md", ".agents/AUDIT-SPEC.md")]}
        (self.tmp / "AUDIT-SPEC.md").write_text("spec\n", encoding="utf-8")
        code, problems, exc = tsc._execute_transaction(self.tmp, plan, "5.2.0")
        self.assertEqual(code, tsc.EXIT_OK)
        manifest = json.loads(tsc.read_text(
            self.tmp / ".agents" / ".tsc-backup" / "manifest.json"))
        self.assertEqual(manifest["moves"],
                         [{"from": "AUDIT-SPEC.md", "to": ".agents/AUDIT-SPEC.md"}])
        self.assertTrue((self.tmp / ".agents" / "AUDIT-SPEC.md").is_file())
        self.assertFalse((self.tmp / "AUDIT-SPEC.md").exists())


class RollbackSafetyAuditTests(unittest.TestCase):
    """A-02：回滚未彻底时备份清单必须保留，成功语不得照发。"""

    def setUp(self):
        import shutil
        self.tmp = Path(tempfile.mkdtemp(prefix="tsc-a02-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.backup = self.tmp / ".agents" / ".tsc-backup"
        self.backup.mkdir(parents=True)

    def _manifest(self, files):
        (self.backup / "manifest.json").write_text(json.dumps(
            {"schema": 2, "contract_version": "5.2.0", "files": files, "moves": []},
            ensure_ascii=False), encoding="utf-8")

    def test_blocked_restore_keeps_manifest_for_retry(self):
        # 目标被目录占位 → 还原失败：清单保留、可重试，绝不毁掉唯一的回滚凭据
        self._manifest([{"path": "AGENTS.md", "action": "modify", "content": "old\n"}])
        (self.tmp / "AGENTS.md").mkdir()
        rc = tsc.cmd_rollback(self.tmp)
        self.assertEqual(rc, tsc.EXIT_IO)
        self.assertTrue((self.backup / "manifest.json").is_file(), "清单必须保留供重试")
        rc2 = tsc.cmd_rollback(self.tmp)  # 修复后二次 rollback 仍可用（清单还在）
        self.assertEqual(rc2, tsc.EXIT_IO)

    def test_dry_run_rejected_for_rollback_and_update(self):
        """A-03：rollback/update 的 --dry-run 显式拒绝（rc=3），不得静默真执行。"""
        (self.backup / "manifest.json").write_text(json.dumps(
            {"schema": 2, "contract_version": "5.2.0", "files": [], "moves": []}), encoding="utf-8")
        marker = self.tmp / "AGENTS.md"
        marker.write_text("intact\n", encoding="utf-8")
        rc = tsc.main(["rollback", "--dry-run", "--project", str(self.tmp)])
        self.assertEqual(rc, tsc.EXIT_STATE)
        self.assertEqual(marker.read_text(encoding="utf-8"), "intact\n", "拒绝时也不得动文件")
        self.assertTrue((self.backup / "manifest.json").is_file())
        rc = tsc.main(["update", "--dry-run"])
        self.assertEqual(rc, tsc.EXIT_STATE)


class NodeLegacyUpgradeAuditTests(unittest.TestCase):
    """A-06：Node 项目旧部署的无标记 pre-commit 必须能走一次性升级。"""

    def setUp(self):
        import shutil
        self.tmp = Path(tempfile.mkdtemp(prefix="tsc-a06-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_node_legacy_precommit_upgrades_not_skipped(self):
        (self.tmp / "package.json").write_text("{}", encoding="utf-8")
        template = tsc.read_text(SKILL / "templates/enforcement/.pre-commit-config.yaml")
        # 旧版部署形态：正文与模板一致、只缺标记行（Node 项目保留 node 区块）
        lines = [ln for ln in template.splitlines()
                 if not tsc.is_marker_line(ln, tsc.MANAGED_MARKER)]
        tsc.write_text_atomic(self.tmp / ".pre-commit-config.yaml", "\n".join(lines) + "\n")
        deploy, update, skip = tsc._enforce_actions(self.tmp, SKILL, AGENTS_SAMPLE)
        self.assertIn(".pre-commit-config.yaml", [n for n, _ in update],
                      "Node 旧部署文件必须能一次性升级为托管版，而不是被误判'项目已接管'")
        self.assertEqual([n for n, _ in skip], [])


class StatusLegacyWordingAuditTests(unittest.TestCase):
    """A-10：status 对'能自动迁移'与'目标被占位'必须区分措辞。"""

    def setUp(self):
        import shutil
        import io
        from contextlib import redirect_stdout
        self.tmp = Path(tempfile.mkdtemp(prefix="tsc-a10-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "AGENTS.md").write_text(AGENTS_SAMPLE, encoding="utf-8")

    def _status_output(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            tsc.cmd_status(self.tmp, None, as_json=False)
        return buf.getvalue()

    def _make_legacy_test_dir(self):
        (self.tmp / "test").mkdir()
        (self.tmp / "test" / "EVAL-SET.md").write_text("x\n", encoding="utf-8")
        (self.tmp / "test" / "TEST-MANUAL.md").write_text("x\n", encoding="utf-8")

    def test_migratable_legacy_promises_auto_move(self):
        self._make_legacy_test_dir()
        out = self._status_output()
        self.assertIn("会自动搬进", out)

    def test_blocked_legacy_warns_instead_of_promising(self):
        self._make_legacy_test_dir()
        (self.tmp / ".agents").mkdir()
        (self.tmp / ".agents" / "test").mkdir()  # 目标被占位 → 搬不动
        out = self._status_output()
        self.assertIn("无法自动迁移", out)
        self.assertNotIn("会自动搬进", out)


class PlaceholderConsistencyAuditTests(unittest.TestCase):
    """A-04②：§2 占位时 check-config 与 CI 同口径（从严 rc=1）。"""

    def setUp(self):
        import shutil
        self.tmp = Path(tempfile.mkdtemp(prefix="tsc-a04-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "AGENTS.md").write_text(AGENTS_SAMPLE.replace(
            "| 测试 (Test) | pytest |", "| 测试 (Test) | %s |" % tsc.PLACEHOLDER), encoding="utf-8")
        (self.tmp / ".agents").mkdir()
        (self.tmp / ".agents" / "project.py").write_text(
            "FMT_CHECK_CMD = None\nLINT_CMD = None\nTEST_CMD = None\nBUILD_CMD = None\n",
            encoding="utf-8")

    def test_placeholder_fails_check_config_with_actionable_message(self):
        import io
        from contextlib import redirect_stdout
        buf_err = io.StringIO()
        import contextlib
        with contextlib.redirect_stderr(buf_err), redirect_stdout(io.StringIO()):
            rc = tsc.cmd_check_config(self.tmp)
        self.assertEqual(rc, tsc.EXIT_MERGE)
        self.assertIn("[自动填充]", buf_err.getvalue())


class VerifyConfigTypeAuditTests(unittest.TestCase):
    """最终审查 F-01：AST 白名单合法接受的 list/int 值不得让 verify 裸崩
    （TypeError traceback），必须干净退出 rc=3 并指明修正位置。"""

    def setUp(self):
        import shutil
        self.tmp = Path(tempfile.mkdtemp(prefix="tsc-f01-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / ".agents").mkdir()

    def _verify(self, cfg_text):
        (self.tmp / ".agents" / "project.py").write_text(cfg_text, encoding="utf-8")
        import io
        from contextlib import redirect_stdout, redirect_stderr
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            rc = tsc.main(["verify", "--project", str(self.tmp)])
        return rc, out.getvalue() + err.getvalue()

    def test_list_command_fails_clean(self):
        rc, out = self._verify('TEST_CMD = ["echo", "hi"]\n')
        self.assertEqual(rc, tsc.EXIT_STATE)
        self.assertIn("必须是字符串", out)
        self.assertNotIn("Traceback", out)

    def test_bad_timeout_fails_clean(self):
        rc, out = self._verify('TEST_CMD = "echo ok"\nGATE_TIMEOUTS = {"TEST_CMD": "abc"}\n')
        self.assertEqual(rc, tsc.EXIT_STATE)
        self.assertIn("无法解释为秒数", out)
        self.assertNotIn("Traceback", out)

    def test_numeric_timeout_still_works(self):
        # 合法形态（数字字符串/整数）不受影响
        rc, out = self._verify(
            'TEST_CMD = "echo ok"\nGATE_TIMEOUTS = {"TEST_CMD": 300}\n')
        self.assertEqual(rc, tsc.EXIT_OK, out)


if __name__ == "__main__":
    unittest.main()

