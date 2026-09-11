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
        agents_md = self.tmp / "AGENTS.md"
        agents_md.write_text(
            agents_md.read_text(encoding="utf-8").replace(
                "| 格式化 (Format) | 无 | — |\n", ""
            ),
            encoding="utf-8",
        )
        code, out = run_script("install", "--from", str(REPO), "--project", str(self.tmp))
        self.assertEqual(code, 1, out)
        self.assertIn("缺少字段", out)


class VerifyAndCheckConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tsc-verify-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        code, out = run_script("install", "--from", str(REPO), "--project", str(self.tmp))
        assert code == 0, out

    def test_all_skip_reports_fake_green(self):
        code, out = run_script("verify", "--project", str(self.tmp))
        self.assertEqual(code, 0)
        self.assertIn("假绿", out)

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
