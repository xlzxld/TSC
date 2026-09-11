# -*- coding: utf-8 -*-
"""tsc.py 回归测试（仅标准库，零依赖）。

运行：python -m unittest discover -s .agents/test -p "test_*.py"

覆盖面：
- §2 切分 / 合并保真 / 结构签名（compose_agents_md 不得吞掉项目定制）
- 路径归一（Git Bash 的 /c/... 风格）
- 执法包归属三态：新部署 / 托管更新 / 项目接管跳过 / 旧版无标记一次性迁移
- install 端到端（7 个落盘文件、gate.yml 分支名跟随 §2）
- sync 同版本幂等早退；结构变更拒绝写入（退出码 1）
- verify：全 skip 时"假绿"警告、配置命令的退出码原样传递
- check-config：project.py 缺变量时显式报不一致
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tsc  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / ".agents" / "tsc.py"

# 与仓库根 AGENTS.md §2 同构的样例（主干分支取 master，用于验证分支名跟随）
AGENTS_SAMPLE = """# 标题

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


def run_script(*args):
    """以子进程跑 tsc.py，返回 (退出码, 合并后的 stdout+stderr)。"""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)] + list(args),
        capture_output=True,
    )
    out = (proc.stdout + proc.stderr).decode("utf-8", errors="replace")
    return proc.returncode, out


def gate_inline_source():
    """从 gate.yml 抽取内联 Python（模拟 YAML run:| 折叠后的效果：去公共缩进）。

    CI 聚合壳与本地 tsc.py 是"同一命令源的两套执行壳"，此抽取器让测试
    能直接执行 CI 侧真身，防止两套壳判定漂移。
    """
    lines = tsc.read_text(REPO / ".agents" / "enforcement" / "gate.yml").split("\n")
    starts = [i for i, ln in enumerate(lines) if "<<'PYEOF'" in ln]
    assert len(starts) == 1, "gate.yml 应恰好含一个内联 Python heredoc"
    body = []
    for ln in lines[starts[0] + 1:]:
        if ln.strip() == "PYEOF":
            break
        body.append(ln)
    indent = min(len(ln) - len(ln.lstrip()) for ln in body if ln.strip())
    return "\n".join(ln[indent:] for ln in body)


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
        # 删掉一行（字段缺失）
        shrunk = AGENTS_SAMPLE.replace("| 格式化 (Format) | black --check | ✅ 0 差异 |\n", "")
        pr_cols, pr_labels = tsc.section2_signature(tsc.section2_text(shrunk))
        missing = [lab for lab in up_labels if lab not in pr_labels]
        self.assertEqual(missing, ["格式化 (Format)"])
        # 列数变化（表头少一列——签名以表头为列定义）
        drifted = AGENTS_SAMPLE.replace(
            "| 项 | 命令 / 取值 | 验证条件 |", "| 项 | 命令 / 取值 |"
        )
        dr_cols, _ = tsc.section2_signature(tsc.section2_text(drifted))
        self.assertNotEqual(len(up_cols), len(dr_cols))


class PathTests(unittest.TestCase):
    def test_passthrough(self):
        self.assertEqual(tsc.normalize_path_arg("C:/foo/bar"), "C:/foo/bar")
        self.assertEqual(tsc.normalize_path_arg("/tmp/normal"), "/tmp/normal")

    @unittest.skipUnless(os.name == "nt", "MSYS 路径还原仅 Windows 生效")
    def test_msys_style_on_windows(self):
        self.assertEqual(tsc.normalize_path_arg("/c/Users/x"), "C:/Users/x")


class EnforceOwnershipTests(unittest.TestCase):
    """执法包归属三态：直接调 _enforce_actions（判定单源）。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tsc-own-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def actions(self, agents_text=AGENTS_SAMPLE):
        return tsc._enforce_actions(self.tmp, REPO, agents_text)

    def test_fresh_deploy(self):
        deploy, update, skip = self.actions()
        self.assertEqual(len(deploy), 3)
        self.assertEqual(update, [])
        self.assertEqual(skip, [])

    def test_managed_same_content_is_noop(self):
        _, _, _ = self.actions()
        # 真跑一次写盘（不走 dry-run 的内部路径）
        tsc.deploy_enforcement(self.tmp, REPO, AGENTS_SAMPLE, dry_run=False)
        deploy, update, skip = self.actions()
        self.assertEqual(deploy, [])
        self.assertEqual(update, [])
        self.assertEqual(skip, [])

    def test_managed_drift_gets_update(self):
        tsc.deploy_enforcement(self.tmp, REPO, AGENTS_SAMPLE, dry_run=False)
        target = self.tmp / "commitlint.config.js"
        text = tsc.read_text(target).replace("config-conventional", "config-conventional ")  # 托管件被旧版模板演进"甩开"
        tsc.write_text_atomic(target, text)
        deploy, update, skip = self.actions()
        self.assertEqual([n for n, _ in update], ["commitlint.config.js"])
        self.assertEqual(skip, [])

    def test_user_takeover_is_skipped(self):
        tsc.deploy_enforcement(self.tmp, REPO, AGENTS_SAMPLE, dry_run=False)
        target = self.tmp / "commitlint.config.js"
        lines = [ln for ln in tsc.read_text(target).splitlines() if tsc.MANAGED_MARKER not in ln]
        lines.append("module.exports = { extends: ['@commitlint/config-conventional'], rules: {} };")
        tsc.write_text_atomic(target, "\n".join(lines) + "\n")
        deploy, update, skip = self.actions()
        self.assertEqual(deploy, [])
        self.assertEqual(update, [])
        self.assertEqual([(n, why) for n, why in skip], [("commitlint.config.js", "内容已被项目改过")])

    def test_legacy_markerless_migrates_once(self):
        # 旧版部署：无标记、正文与模板一致 → 一次性升级为托管版
        src = REPO / ".agents" / "enforcement" / "commitlint.config.js"
        body = "\n".join(ln for ln in tsc.read_text(src).splitlines() if tsc.MANAGED_MARKER not in ln)
        target = self.tmp / "commitlint.config.js"
        target.write_text(body + "\n", encoding="utf-8")
        deploy, update, skip = self.actions()
        self.assertEqual([n for n, _ in update], ["commitlint.config.js"])

    def test_gate_yml_branch_follows_section2(self):
        tsc.deploy_enforcement(self.tmp, REPO, AGENTS_SAMPLE, dry_run=False)
        gate = tsc.read_text(self.tmp / ".github" / "workflows" / "gate.yml")
        self.assertIn("branches: [master]", gate)  # §2 主干分支 = master
        self.assertNotIn("branches: [main]", gate)

    def test_self_target_skips_enforcement(self):
        # 母版自举不得把执法包铺进自己根目录（保持上游纯净）
        self.assertEqual(tsc._enforce_actions(REPO, REPO, AGENTS_SAMPLE), ([], [], []))


class LegacyMigrationTests(unittest.TestCase):
    """回归（v3.1.2 A-01）：旧结构迁移不得误搬项目自己的 test/、enforcement/。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tsc-legacy-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_fresh_install_leaves_unrelated_dirs_alone(self):
        # 从未部署过契约的项目（根目录无 AGENTS.md），根 test/ 是项目自己的，不许搬
        (self.tmp / "test").mkdir(parents=True)
        (self.tmp / "test" / "test_user_own.py").write_text("print('own')\n", encoding="utf-8")
        code, out = run_script("install", "--from", str(REPO), "--project", str(self.tmp))
        self.assertEqual(code, 0, out)
        self.assertTrue((self.tmp / "test" / "test_user_own.py").is_file())
        self.assertNotIn("迁移", out)
        self.assertFalse((self.tmp / ".agents" / "test").exists())

    def test_contracted_project_own_test_dir_not_migrated(self):
        # 已部署过契约的项目，不带契约内容签名的 test/ 同样不许搬
        code, out = run_script("install", "--from", str(REPO), "--project", str(self.tmp))
        self.assertEqual(code, 0, out)
        (self.tmp / "test").mkdir()
        (self.tmp / "test" / "test01x.py").write_text("print('own')\n", encoding="utf-8")
        code, out = run_script("install", "--from", str(REPO), "--project", str(self.tmp))
        self.assertEqual(code, 0, out)
        self.assertTrue((self.tmp / "test" / "test01x.py").is_file())
        self.assertNotIn("迁移", out)

    def test_old_layout_with_signatures_migrates(self):
        # 真·旧结构（v2 布局：根 AGENTS.md + 带契约签名的 test/、enforcement/）照常迁移
        (self.tmp / "AGENTS.md").write_text(AGENTS_SAMPLE, encoding="utf-8")
        (self.tmp / "test").mkdir()
        (self.tmp / "test" / "EVAL-SET.md").write_text("x\n", encoding="utf-8")
        (self.tmp / "enforcement").mkdir()
        (self.tmp / "enforcement" / "gate.yml").write_text("x\n", encoding="utf-8")
        code, out = run_script("install", "--from", str(REPO), "--project", str(self.tmp))
        self.assertEqual(code, 0, out)
        self.assertTrue((self.tmp / ".agents" / "test" / "EVAL-SET.md").is_file())
        self.assertTrue((self.tmp / ".agents" / "enforcement" / "gate.yml").is_file())
        self.assertFalse((self.tmp / "test").exists())
        self.assertFalse((self.tmp / "enforcement").exists())

    def test_dry_run_reports_will_move_not_moved(self):
        # 回归（v3.1.2 A-05/A-06）：dry-run 不得说"已迁移"，全新安装也不得冒出"版本相同"
        (self.tmp / "AGENTS.md").write_text(AGENTS_SAMPLE, encoding="utf-8")
        (self.tmp / "test").mkdir()
        (self.tmp / "test" / "EVAL-SET.md").write_text("x\n", encoding="utf-8")
        code, out = run_script(
            "install", "--from", str(REPO), "--project", str(self.tmp), "--dry-run"
        )
        self.assertEqual(code, 0, out)
        self.assertIn("将迁移到", out)
        self.assertNotIn("已迁移", out)
        self.assertNotIn("版本相同", out)
        self.assertIn("未写入任何文件", out)
        self.assertTrue((self.tmp / "test" / "EVAL-SET.md").is_file())


class SourceRecordTests(unittest.TestCase):
    """回归（v3.1.2 A-02/A-04）：.source 必须始终记录本次实际使用的上游。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tsc-src-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _make_old_upstream(self, root):
        root.mkdir(parents=True)
        (root / "AGENTS.md").write_text(AGENTS_SAMPLE, encoding="utf-8")
        (root / "VERSION").write_text("3.0.0\n", encoding="utf-8")
        agents = root / ".agents"
        agents.mkdir()
        (agents / "project.example.py").write_text("TEST_CMD = None\n", encoding="utf-8")
        return root

    def test_explicit_from_repoints_source(self):
        # 显式 --from 新上游成功后，.source 必须跟着换；否则下次裸 sync 会静默降级回旧上游
        old = self._make_old_upstream(self.tmp / "old-skill")
        proj = self.tmp / "proj"
        proj.mkdir()
        code, out = run_script("install", "--from", str(old), "--project", str(proj))
        self.assertEqual(code, 0, out)
        self.assertEqual(tsc.read_text(proj / ".agents" / ".source").strip(), str(old))
        code, out = run_script("sync", "--from", str(REPO), "--project", str(proj))
        self.assertEqual(code, 0, out)
        self.assertEqual(tsc.read_text(proj / ".agents" / ".source").strip(), str(REPO))
        # 换源后裸 sync 不得静默降级：上游=本仓库、版本同、执法包已对齐 → 应早退，
        # 且 VERSION 保持本仓库版本（修复前会回落到旧上游的 3.0.0）
        code, out = run_script("sync", "--project", str(proj))
        self.assertEqual(code, 0, out)
        self.assertIn("已是最新", out)
        self.assertEqual(
            tsc.read_text(proj / ".agents" / "VERSION").strip(),
            tsc.upstream_version(REPO),
        )

    def test_empty_source_gets_rewritten(self):
        # 空的 .source 既不算缺失也不算死路径，旧版永远不会补写——现在必须回填
        proj = self.tmp / "proj"
        proj.mkdir()
        code, out = run_script("install", "--from", str(REPO), "--project", str(proj))
        self.assertEqual(code, 0, out)
        (proj / ".agents" / ".source").write_text("", encoding="utf-8")
        code, out = run_script("sync", "--project", str(proj))
        self.assertEqual(code, 0, out)
        self.assertEqual(tsc.read_text(proj / ".agents" / ".source").strip(), str(REPO))


class InstallSyncE2ETests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tsc-e2e-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_install_lands_seven_files(self):
        code, out = run_script("install", "--from", str(REPO), "--project", str(self.tmp))
        self.assertEqual(code, 0, out)
        expected = [
            "AGENTS.md",
            ".agents/project.py",
            ".agents/VERSION",
            ".agents/.source",
            ".pre-commit-config.yaml",
            "commitlint.config.js",
            ".github/workflows/gate.yml",
        ]
        for rel in expected:
            self.assertTrue((self.tmp / rel).is_file(), "缺少 %s" % rel)
        gate = (self.tmp / ".github" / "workflows" / "gate.yml").read_text(encoding="utf-8")
        self.assertIn("branches: [main]", gate)  # 本仓库 §2 主干分支 = main
        version = (self.tmp / ".agents" / "VERSION").read_text(encoding="utf-8").strip()
        self.assertEqual(version, tsc.upstream_version(REPO))

    def test_install_dry_run_previews_all_seven_files(self):
        # 回归：dry-run 预览必须列全 7 个将写文件（旧版漏报 project.py 与 .source）
        code, out = run_script("install", "--from", str(REPO), "--project", str(self.tmp), "--dry-run")
        self.assertEqual(code, 0, out)
        self.assertIn("未写入任何文件", out)
        for rel in [
            "AGENTS.md",
            ".agents/VERSION",
            ".agents/project.py",
            ".agents/.source",
            ".github/workflows/gate.yml",
            ".pre-commit-config.yaml",
            "commitlint.config.js",
        ]:
            self.assertIn(rel, out, "dry-run 漏报 %s" % rel)
        self.assertEqual(list(self.tmp.rglob("*")), [])  # dry-run 零写盘

    def test_dead_source_falls_back_and_gets_repaired(self):
        # 回归（P2-1）：技能目录搬家（.source 死路径）不得让存量项目 sync/status 直接 rc=3
        code, _ = run_script("install", "--from", str(REPO), "--project", str(self.tmp))
        self.assertEqual(code, 0)
        dead = self.tmp / "vanish"  # 从未存在的路径，模拟技能目录被搬走
        (self.tmp / ".agents" / ".source").write_text(str(dead) + "\n", encoding="utf-8")
        code, out = run_script("status", "--project", str(self.tmp))  # 只读命令：回退但不改记录
        self.assertEqual(code, 0, out)
        self.assertIn("已失效", out)
        self.assertIn(str(REPO), out)  # 回退到脚本所在仓库（当前即本仓库）
        self.assertEqual(tsc.read_text(self.tmp / ".agents" / ".source").strip(), str(dead))
        code, out = run_script("sync", "--project", str(self.tmp), "--dry-run")
        self.assertEqual(code, 0, out)
        self.assertIn(".agents/.source", out)
        self.assertIn("未写入任何文件", out)
        code, out = run_script("sync", "--project", str(self.tmp))  # 写入命令：顺手修正死记录
        self.assertEqual(code, 0, out)
        self.assertEqual(
            tsc.read_text(self.tmp / ".agents" / ".source").strip(), str(REPO)
        )

    def test_sync_same_version_is_noop(self):
        code, _ = run_script("install", "--from", str(REPO), "--project", str(self.tmp))
        self.assertEqual(code, 0)
        code, out = run_script("sync", "--from", str(REPO), "--project", str(self.tmp))
        self.assertEqual(code, 0, out)
        self.assertIn("已是最新", out)

    def test_install_keeps_custom_section2(self):
        code, _ = run_script("install", "--from", str(REPO), "--project", str(self.tmp))
        self.assertEqual(code, 0)
        agents_md = self.tmp / "AGENTS.md"
        # 对取值不敏感：无论上游 §2 当前填什么，正则改写"测试"行再复跑，定制必须保留
        import re
        agents_md.write_text(
            re.sub(r"\| 测试 \(Test\) \|[^|]*\|", "| 测试 (Test) | pytest -q |",
                   agents_md.read_text(encoding="utf-8")),
            encoding="utf-8",
        )
        code, out = run_script("install", "--from", str(REPO), "--project", str(self.tmp))
        self.assertEqual(code, 0, out)
        self.assertIn("| 测试 (Test) | pytest -q |", agents_md.read_text(encoding="utf-8"))

    def test_install_rejects_section2_structure_drift(self):
        code, _ = run_script("install", "--from", str(REPO), "--project", str(self.tmp))
        self.assertEqual(code, 0)
        import re
        agents_md = self.tmp / "AGENTS.md"
        agents_md.write_text(
            re.sub(r"\| 格式化 \(Format\) \|[^\n]*\|\n", "",
                   agents_md.read_text(encoding="utf-8")),
            encoding="utf-8",
        )
        code, out = run_script("install", "--from", str(REPO), "--project", str(self.tmp))
        self.assertEqual(code, 1, out)
        self.assertIn("缺少字段", out)

    def test_fresh_install_section2_is_placeholder(self):
        # 修复回归：新装项目不得继承母版仓库自己的 §2 取值（如"Markdown 文档 + Python 3"）
        code, out = run_script("install", "--from", str(REPO), "--project", str(self.tmp))
        self.assertEqual(code, 0, out)
        text = (self.tmp / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("| 测试 (Test) | [自动填充] |", text)
        self.assertIn("| 主干分支 | [自动填充] |", text)
        self.assertNotIn("Markdown 文档 + Python 3", text)

    def test_gate_yml_keeps_default_branch_when_trunk_is_none(self):
        # 回归（v3.1.3）：§2 主干分支填"无"（如非 git 项目）时，gate.yml 不得写进坏分支名
        sample = AGENTS_SAMPLE.replace("| 主干分支 | master |", "| 主干分支 | 无 |")
        tsc.deploy_enforcement(self.tmp, REPO, sample, dry_run=False)
        gate = tsc.read_text(self.tmp / ".github" / "workflows" / "gate.yml")
        self.assertIn("branches: [main]", gate)
        self.assertNotIn("branches: [无", gate)
        for ln in gate.splitlines():
            if "branches:" in ln:
                self.assertNotIn("自动填充", ln)

    def test_fresh_install_gate_yml_keeps_default_branch(self):
        # 占位符不得流进 gate.yml 的 branches:
        code, out = run_script("install", "--from", str(REPO), "--project", str(self.tmp))
        self.assertEqual(code, 0, out)
        gate = (self.tmp / ".github" / "workflows" / "gate.yml").read_text(encoding="utf-8")
        self.assertIn("branches: [main]", gate)
        # 不变量收窄到 branches 值：占位符/坏值不得出现在分支配置里
        # （gate.yml 内联校验代码合法引用"[自动填充]"哨兵串，不属泄漏）
        for ln in gate.splitlines():
            if "branches:" in ln:
                self.assertNotIn("[自动填充]", ln)
        self.assertNotIn("branches: [[自动填充]]", gate)

    def test_status_flags_unfilled_section2(self):
        # 修复回归：§2 全占位时 status 必须报"未填好"，不得误报"是"
        code, _ = run_script("install", "--from", str(REPO), "--project", str(self.tmp))
        self.assertEqual(code, 0)
        code, out = run_script("status", "--from", str(REPO), "--project", str(self.tmp))
        self.assertEqual(code, 0, out)
        self.assertIn("否，仍有 [自动填充] 占位", out)


class StatusTests(unittest.TestCase):
    """回归（v3.1.2 A-03）：status 对残缺 AGENTS.md 必须如实报告。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tsc-status-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_status_reports_missing_section2(self):
        proj = self.tmp / "proj"
        proj.mkdir()
        (proj / "AGENTS.md").write_text("# T\n\nno section two here\n", encoding="utf-8")
        code, out = run_script("status", "--from", str(REPO), "--project", str(proj))
        self.assertEqual(code, 0, out)
        self.assertIn("找不到 §2 章节", out)
        self.assertNotIn("是否填好：是", out)


class RobustnessTests(unittest.TestCase):
    """回归（v3.1.2 A-07~A-10）：异常路径与解析健壮性。"""

    def test_normalize_accepts_drive_root(self):
        # 回归（A-10）：/c/ 恰好三个字符，也要归一成 C:/
        if os.name != "nt":
            self.skipTest("MSYS 路径还原仅 Windows 生效")
        self.assertEqual(tsc.normalize_path_arg("/c/"), "C:/")

    def test_placeholder_skips_header_without_magic_label(self):
        # 回归（A-09）：表头首列不叫"项"时，表头行的取值列也不得被占位化
        sample = AGENTS_SAMPLE.replace(
            "| 项 | 命令 / 取值 | 验证条件 |", "| 名称 | 值 | 说明 |"
        )
        out = tsc.section2_to_placeholder(sample)
        self.assertIn("| 名称 | 值 | 说明 |", out)
        self.assertIn("| 测试 (Test) | [自动填充] |", out)

    def test_atomic_write_cleans_tmp_on_failure(self):
        # 回归（A-08）：os.replace 失败时不得残留 .tsc-tmp，且原异常必须抛出
        from unittest import mock

        target_dir = Path(tempfile.mkdtemp(prefix="tsc-tmp-"))
        self.addCleanup(shutil.rmtree, target_dir, True)
        target = target_dir / "f.txt"
        with mock.patch("os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                tsc.write_text_atomic(target, "x")
        self.assertEqual(list(target_dir.glob("*.tsc-tmp")), [])

    def test_main_maps_oserror_to_exit_2(self):
        # 回归（A-07）：底层 IO 异常不得裸 traceback，须归一为退出码 2
        from unittest import mock

        with mock.patch.object(tsc, "find_upstream", side_effect=OSError("boom")):
            code = tsc.main(["status"])
        self.assertEqual(code, 2)


class VerifyAndCheckConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tsc-verify-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        code, out = run_script("install", "--from", str(REPO), "--project", str(self.tmp))
        assert code == 0, out

    def test_all_skip_fails_loud(self):
        # 回归（v3.2.0 P1-01）：全未配置从"假绿警告+rc=0"收紧为"失败 rc=3"，与 CI 同口径
        code, out = run_script("verify", "--project", str(self.tmp))
        self.assertEqual(code, 3, out)
        self.assertIn("假绿", out)
        self.assertNotIn("门禁结论：全绿", out)

    def test_gate_inline_all_skip_exits_3(self):
        # 回归（v3.2.0 P1-01）：CI 内联壳必须同样把全 skip 判为失败 rc=3
        proc = subprocess.run(
            [sys.executable, "-c", gate_inline_source()],
            cwd=str(self.tmp), capture_output=True,
        )
        combined = (proc.stdout + proc.stderr).decode("utf-8", errors="replace")
        self.assertEqual(proc.returncode, 3, combined)
        self.assertIn("假绿", combined)

    def _gate_inline_run(self):
        return subprocess.run(
            [sys.executable, "-c", gate_inline_source()],
            cwd=str(self.tmp), capture_output=True,
        )

    def _adapted_section2(self, test_cmd):
        """把全新安装的占位 §2 整表适配为真实取值（测试行用 test_cmd）。"""
        agents = self.tmp / "AGENTS.md"
        t = agents.read_text(encoding="utf-8")
        t = re.sub(r"\| 技术栈 \|[^\n]*\|", "| 技术栈 | Demo | — |", t, count=1)
        t = re.sub(r"\| 构建 \(Build\) \|[^\n]*\|", "| 构建 (Build) | 无 | ✅ 无构建产物 |", t, count=1)
        t = re.sub(r"\| 静态检查 \(Lint\) \|[^\n]*\|", "| 静态检查 (Lint) | 无 | ✅ 无 |", t, count=1)
        t = re.sub(r"\| 格式化 \(Format\) \|[^\n]*\|", "| 格式化 (Format) | 无 | ✅ 无差异 |", t, count=1)
        t = re.sub(r"\| 主干分支 \|[^\n]*\|", "| 主干分支 | main | ✅ 禁止直推 |", t, count=1)
        t = re.sub(r"\| 已知豁免清单 \|[^\n]*\|", "| 已知豁免清单 | 无 | 白名单 |", t, count=1)
        t = re.sub(r"\| 测试 \(Test\) \|[^\n]*\|", "| 测试 (Test) | `%s` | ✅ 全绿 |" % test_cmd, t, count=1)
        agents.write_text(t, encoding="utf-8")
        return agents

    def test_gate_inline_flags_config_mismatch(self):
        # 回归（v3.2.0 P1-02）：§2 与 project.py 不一致时，CI 内联壳必须 rc=1 拦下
        (self.tmp / ".agents" / "project.py").write_text(
            'FMT_CHECK_CMD = None\nLINT_CMD = None\nTEST_CMD = "echo from-project-py"\nBUILD_CMD = None\n',
            encoding="utf-8")
        self._adapted_section2("echo from-section2")
        proc = self._gate_inline_run()
        combined = (proc.stdout + proc.stderr).decode("utf-8", errors="replace")
        self.assertEqual(proc.returncode, 1, combined)
        self.assertIn("不一致", combined)

    def test_gate_inline_agrees_with_check_config(self):
        # 两套壳同判定：同一不一致夹具，本地 check-config 与 CI 内联壳都 rc=1
        (self.tmp / ".agents" / "project.py").write_text(
            'FMT_CHECK_CMD = None\nLINT_CMD = None\nTEST_CMD = "echo from-project-py"\nBUILD_CMD = None\n',
            encoding="utf-8")
        self._adapted_section2("echo from-section2")
        code, out = run_script("check-config", "--project", str(self.tmp))
        self.assertEqual(code, 1, out)
        proc = self._gate_inline_run()
        self.assertEqual(proc.returncode, 1)

    def test_gate_inline_consistent_config_runs_gates(self):
        # 同源且已配置 → 校验通过、命令真实执行、rc=0
        (self.tmp / ".agents" / "project.py").write_text(
            'FMT_CHECK_CMD = None\nLINT_CMD = None\nTEST_CMD = "echo gate-ok"\nBUILD_CMD = None\n',
            encoding="utf-8")
        self._adapted_section2("echo gate-ok")
        proc = self._gate_inline_run()
        combined = (proc.stdout + proc.stderr).decode("utf-8", errors="replace")
        self.assertEqual(proc.returncode, 0, combined)
        self.assertIn("同源校验", combined)
        self.assertIn("gate-ok", combined)

    def test_exit_code_passthrough(self):
        # 用辅助脚本规避跨 shell 引号嵌套问题；门禁命令退出码必须原样传递
        probe = self.tmp / "gate_probe.py"
        project_py = self.tmp / ".agents" / "project.py"
        # 嵌入路径统一正斜杠，避免 Windows 反斜杠在 project.py 里被当转义序列
        py_exe = sys.executable.replace("\\", "/")
        probe.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
        project_py.write_text('TEST_CMD = "%s gate_probe.py"\n' % py_exe, encoding="utf-8")
        code, out = run_script("verify", "--project", str(self.tmp))
        self.assertEqual(code, 0, out)
        self.assertIn("退出码：0", out)
        probe.write_text("import sys\nsys.exit(7)\n", encoding="utf-8")
        code, out = run_script("verify", "--project", str(self.tmp))
        self.assertEqual(code, 7, out)
        self.assertIn("退出码：7", out)

    def test_check_config_flags_missing_variable(self):
        project_py = self.tmp / ".agents" / "project.py"
        text = project_py.read_text(encoding="utf-8")
        text = "\n".join(ln for ln in text.splitlines() if not ln.startswith("TEST_CMD"))
        project_py.write_text(text + "\n", encoding="utf-8")
        code, out = run_script("check-config", "--project", str(self.tmp))
        self.assertEqual(code, 1, out)
        self.assertIn("未定义该变量", out)

    def test_check_config_green_when_project_py_matches_section2(self):
        # 把上游自己的 AGENTS.md + project.py 成对放进沙箱——这对配置必须自洽（绿色路径）
        shutil.copyfile(REPO / "AGENTS.md", self.tmp / "AGENTS.md")
        shutil.copyfile(REPO / ".agents" / "project.py", self.tmp / ".agents" / "project.py")
        code, out = run_script("check-config", "--project", str(self.tmp))
        self.assertEqual(code, 0, out)

    def test_fresh_install_prompts_fill(self):
        # 新装项目 project.py 全 None、§2 还没按本项目填——check-config 必须报不一致，
        # 提醒先填 §2 与 project.py，而不是静默通过
        code, out = run_script("check-config", "--project", str(self.tmp))
        self.assertEqual(code, 1, out)
        self.assertIn("不一致", out)


if __name__ == "__main__":
    unittest.main()
