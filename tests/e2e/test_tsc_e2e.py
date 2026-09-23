# -*- coding: utf-8 -*-
"""tsc.py 端到端回归（子进程跑真 CLI，目标 <30s）。

规格 §10 场景对照：
升级：旧版本 → 新版本裸 sync 必升级；.source 指向旧/失效路径不阻塞、不被采信；
      非 git 安装副本提示走宿主更新。
安全边界：无 marker 的外部 AGENTS.md 不被 sync/install 接管；--force 显式接管；
      有 marker 只更新托管内容；§2 结构变化仍拒绝自动合并；项目接管的执法包不覆盖。
技能打包：技能目录自包含、SKILL 可发现（单测层覆盖静态约束，这里跑 CLI 真身）。
门禁：verify 超时杀进程组返回 124；退出码透传；假绿 rc=3；CI 内联壳与本地同判定。
回滚：sync 后 rollback 恢复上一状态；无可回滚记录时报 3。
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SKILL = REPO / "skills" / "tsc"
SCRIPT = SKILL / "scripts" / "tsc.py"

# 跨平台门禁夹具：`true` / `sleep` 是 POSIX 专属，Windows 上没有（A-02）。
QUICK_CMD = '"%s" -c "pass"' % sys.executable
SLOW_CMD = '"%s" -c "import time;time.sleep(60)"' % sys.executable


def run_script(*args, cwd=None):
    """以子进程跑 tsc.py，返回 (退出码, 合并后的 stdout+stderr)。"""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)] + list(args),
        capture_output=True, cwd=str(cwd) if cwd else None,
    )
    out = (proc.stdout + proc.stderr).decode("utf-8", errors="replace")
    return proc.returncode, out


def gate_inline_source():
    """从 gate.yml 抽取内联 Python（模拟 YAML run:| 折叠后的效果：去公共缩进）。

    CI 聚合壳与本地 tsc.py 是"同一命令源的两套执行壳"，此抽取器让测试
    能直接执行 CI 侧真身，防止两套壳判定漂移。
    """
    lines = (SKILL / "templates" / "enforcement" / "gate.yml").read_text(encoding="utf-8").split("\n")
    starts = [i for i, ln in enumerate(lines) if "<<'PYEOF'" in ln]
    assert len(starts) == 1, "gate.yml 应恰好含一个内联 Python heredoc"
    body = []
    for ln in lines[starts[0] + 1:]:
        if ln.strip() == "PYEOF":
            break
        body.append(ln)
    indent = min(len(ln) - len(ln.lstrip()) for ln in body if ln.strip())
    return "\n".join(ln[indent:] for ln in body)


class E2EBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tsc-e2e-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def install(self, proj=None, *extra):
        proj = proj or self.tmp
        return run_script("install", "--project", str(proj), *extra)

    def adapt_section2(self, proj, test_cmd="echo t-ok"):
        """把全新安装的占位 §2 适配为真实取值（模拟 BOOTSTRAP 填充）。"""
        agents = Path(proj) / "AGENTS.md"
        t = agents.read_text(encoding="utf-8")
        t = re.sub(r"\| 技术栈 \|[^\n]*\|", "| 技术栈 | Demo | — |", t, count=1)
        t = re.sub(r"\| 构建 \(Build\) \|[^\n]*\|", "| 构建 (Build) | 无 | ✅ 无构建产物 |", t, count=1)
        t = re.sub(r"\| 静态检查 \(Lint\) \|[^\n]*\|", "| 静态检查 (Lint) | 无 | ✅ 无 |", t, count=1)
        t = re.sub(r"\| 格式化 \(Format\) \|[^\n]*\|", "| 格式化 (Format) | 无 | ✅ 无差异 |", t, count=1)
        t = re.sub(r"\| 主干分支 \|[^\n]*\|", "| 主干分支 | main | ✅ 禁止直推 |", t, count=1)
        t = re.sub(r"\| 已知豁免清单 \|[^\n]*\|", "| 已知豁免清单 | 无 | 白名单 |", t, count=1)
        t = re.sub(r"\| 测试 \(Test\) \|[^\n]*\|",
                   lambda _m: "| 测试 (Test) | `%s` | ✅ 全绿 |" % test_cmd,
                   t, count=1)
        agents.write_text(t, encoding="utf-8")
        return agents

    def set_project_py(self, proj, test_cmd):
        (Path(proj) / ".agents" / "project.py").write_text(
            'FMT_CHECK_CMD = None\nLINT_CMD = None\nTEST_CMD = %r\nBUILD_CMD = None\n' % test_cmd,
            encoding="utf-8")


class InstallTests(E2EBase):
    def test_python_only_install_lands_eight_files_no_node(self):
        """P1-04：Python-only 项目不引入任何 npm 依赖。"""
        code, out = self.install()
        self.assertEqual(code, 0, out)
        expected = [
            "AGENTS.md",
            ".agents/project.py",
            ".agents/VERSION",
            ".agents/.source",
            ".pre-commit-config.yaml",
            ".github/workflows/gate.yml",
            ".agents/structure_guard.py",
            ".agents/bracket_lint.py",
        ]
        for rel in expected:
            self.assertTrue((self.tmp / rel).is_file(), "缺少 %s" % rel)
        self.assertFalse((self.tmp / "commitlint.config.js").exists())
        gate = (self.tmp / ".github" / "workflows" / "gate.yml").read_text(encoding="utf-8")
        self.assertIn("branches: [main]", gate)  # 本仓库 §2 主干分支 = main
        precommit = (self.tmp / ".pre-commit-config.yaml").read_text(encoding="utf-8")
        self.assertNotIn("npx", precommit)
        self.assertIn("hashFiles('commitlint.config.js') != ''", gate)
        self.assertIn("不部署 commitlint", out)
        version = (self.tmp / ".agents" / "VERSION").read_text(encoding="utf-8").strip()
        self.assertEqual(version, "5.0.0")

    def test_node_install_adds_commitlint(self):
        (self.tmp / "package.json").write_text('{"name": "x"}', encoding="utf-8")
        code, out = self.install()
        self.assertEqual(code, 0, out)
        self.assertTrue((self.tmp / "commitlint.config.js").is_file())
        precommit = (self.tmp / ".pre-commit-config.yaml").read_text(encoding="utf-8")
        self.assertIn("npx", precommit)
        self.assertIn("commitlint 已随执法包部署", out)

    def test_fresh_install_section2_is_placeholder_and_marked(self):
        """新装项目不得继承母版取值；必须带所有权标记。"""
        code, out = self.install()
        self.assertEqual(code, 0, out)
        text = (self.tmp / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("| 测试 (Test) | [自动填充] |", text)
        self.assertIn("| 主干分支 | [自动填充] |", text)
        self.assertNotIn("Python 3（仅标准库）", text)
        self.assertIn("<!-- tsc-managed-contract:v4 -->", text)

    def test_install_dry_run_previews_and_writes_nothing(self):
        code, out = run_script("install", "--project", str(self.tmp), "--dry-run")
        self.assertEqual(code, 0, out)
        self.assertIn("未写入任何文件", out)
        for rel in ["AGENTS.md", ".agents/VERSION", ".agents/project.py", ".agents/.source",
                    ".github/workflows/gate.yml", ".pre-commit-config.yaml"]:
            self.assertIn(rel, out, "dry-run 漏报 %s" % rel)
        self.assertEqual(list(self.tmp.rglob("*")), [])  # dry-run 零写盘

    def test_structured_source_written_as_json(self):
        """P2-08：provenance 是结构化 JSON。"""
        code, out = self.install()
        self.assertEqual(code, 0, out)
        record = json.loads((self.tmp / ".agents" / ".source").read_text(encoding="utf-8"))
        self.assertEqual(record["source"], str(SKILL))
        self.assertEqual(record["version"], "5.0.0")
        self.assertIn("installed_at", record)

    def test_sync_same_state_is_noop(self):
        code, _ = self.install()
        self.assertEqual(code, 0)
        code, out = run_script("sync", "--project", str(self.tmp))
        self.assertEqual(code, 0, out)
        self.assertIn("已是最新", out)

    def test_self_repo_sync_keeps_agents_md(self):
        """母版自举：对自己 sync 不铺执法包、不改动根 AGENTS.md。"""
        before = (REPO / "AGENTS.md").read_bytes()
        code, out = run_script("sync", "--project", str(REPO))
        self.assertEqual(code, 0, out)
        self.assertIn("已是最新", out)
        self.assertEqual((REPO / "AGENTS.md").read_bytes(), before)
        self.assertFalse((REPO / ".pre-commit-config.yaml").exists(),
                         "母版自举不得把执法包铺进仓库根")


class UpgradeTests(E2EBase):
    """规格 §10 升级场景 + P1-01 核心回归。"""

    def _make_v3_project(self):
        """模拟 v3.3.2 旧版安装的项目：无 marker、.source 指向一个已消失的旧技能目录。"""
        code, out = self.install()
        self.assertEqual(code, 0, out)
        agents = self.tmp / "AGENTS.md"
        text = agents.read_text(encoding="utf-8").replace("<!-- tsc-managed-contract:v4 -->\n\n", "")
        text = text.replace("> **版本 v5.0.0**", "> **版本 v3.3.2**")
        agents.write_text(text, encoding="utf-8")
        (self.tmp / ".agents" / "VERSION").write_text("3.3.2\n", encoding="utf-8")
        (self.tmp / ".agents" / ".source").write_text(
            "/nonexistent/old/skills/tsc\n", encoding="utf-8")

    def test_bare_sync_upgrades_legacy_project_despite_stale_source(self):
        """P1-01：旧版项目裸 sync 必须升级到当前本体；.source 旧路径不被采信、不阻塞。"""
        self._make_v3_project()
        code, out = run_script("sync", "--project", str(self.tmp))
        self.assertEqual(code, 0, out)
        self.assertIn("3.3.2 → 5.0.0", out)
        agents = (self.tmp / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("<!-- tsc-managed-contract:v4 -->", agents)
        self.assertEqual((self.tmp / ".agents" / "VERSION").read_text().strip(), "5.0.0")
        record = json.loads((self.tmp / ".agents" / ".source").read_text(encoding="utf-8"))
        self.assertEqual(record["source"], str(SKILL))  # 已修正为实际使用的上游

    def test_source_pointing_to_other_upstream_does_not_win(self):
        """.source 即使指向一个"有效"的别的上游，也只是记录——裸 sync 仍用当前本体。"""
        other = self.tmp / "other-upstream"
        (other / "templates").mkdir(parents=True)
        (other / "VERSION").write_text("0.0.1\n", encoding="utf-8")
        shutil.copyfile(SKILL / "templates/AGENTS.md", other / "templates/AGENTS.md")
        shutil.copyfile(SKILL / "templates/project.example.py",
                        other / "templates/project.example.py")
        code, _ = self.install()
        self.assertEqual(code, 0)
        (self.tmp / ".agents" / ".source").write_text(str(other) + "\n", encoding="utf-8")
        code, out = run_script("sync", "--project", str(self.tmp))
        self.assertEqual(code, 0, out)
        self.assertEqual(
            (self.tmp / ".agents" / "VERSION").read_text().strip(), "5.0.0",
            "裸 sync 后版本必须是当前本体的，不是 .source 指向的旧上游")

    def test_explicit_source_used_for_one_sync_then_repoints_provenance(self):
        other = self.tmp / "up"
        (other / "templates").mkdir(parents=True)
        (other / "VERSION").write_text("9.9.9\n", encoding="utf-8")
        shutil.copyfile(SKILL / "templates/AGENTS.md", other / "templates/AGENTS.md")
        shutil.copyfile(SKILL / "templates/project.example.py",
                        other / "templates/project.example.py")
        code, _ = self.install()
        self.assertEqual(code, 0)
        code, out = run_script("sync", "--source", str(other), "--project", str(self.tmp))
        self.assertEqual(code, 0, out)
        self.assertEqual((self.tmp / ".agents" / "VERSION").read_text().strip(), "9.9.9")
        record = json.loads((self.tmp / ".agents" / ".source").read_text(encoding="utf-8"))
        self.assertEqual(record["version"], "9.9.9")
        # 再裸 sync：回到当前本体
        code, out = run_script("sync", "--project", str(self.tmp))
        self.assertEqual(code, 0, out)
        self.assertEqual((self.tmp / ".agents" / "VERSION").read_text().strip(), "5.0.0")

    def test_update_on_nongit_copy_reports_host_update_path(self):
        """规格 §10：没有 .git 的已安装副本 → 提示宿主升级机制，rc=3。

        夹具在临时目录构造一份无 .git 的插件副本（模拟宿主市场安装），
        从该副本自己调 update——不能直接对本仓库跑：仓库自身是 git 安装，
        update 会走真实 git pull（慢且依赖网络）。
        """
        copy = self.tmp / "installed-tsc"
        shutil.copytree(
            REPO, copy,
            ignore=shutil.ignore_patterns(".git", "__pycache__", ".agents", ".tsc-tmp"),
        )
        proc = subprocess.run(
            [sys.executable, str(copy / "skills" / "tsc" / "scripts" / "tsc.py"), "update"],
            capture_output=True,
        )
        out = (proc.stdout + proc.stderr).decode("utf-8", errors="replace")
        self.assertEqual(proc.returncode, 3, out)
        self.assertIn(".git", out)
        self.assertIn("宿主", out)


class OwnershipBoundaryTests(E2EBase):
    """规格 §10 安全边界：外部 AGENTS.md 绝不被误接管。"""

    FOREIGN = """# 我自己的项目规范

## 约定

- 这是项目自己的规则，不是 TSC 契约。

## 2. 项目环境与验证门禁

| 项 | 命令 / 取值 | 验证条件 |
|---|---|---|
| 技术栈 | Python | — |
| 构建 (Build) | 无 | — |
| 测试 (Test) | pytest | ✅ 全绿 |
| 静态检查 (Lint) | ruff | ✅ 0 错误 |
| 格式化 (Format) | 无 | — |
| 主干分支 | main | ✅ 禁止直推 |
| 已知豁免清单 | 无 | 白名单 |
"""

    def test_sync_refuses_foreign_agents_md(self):
        """P1-03：无 marker 的外部 AGENTS.md，sync 不得全文覆盖。"""
        (self.tmp / "AGENTS.md").write_text(self.FOREIGN, encoding="utf-8")
        original = self.FOREIGN
        code, out = run_script("sync", "--project", str(self.tmp))
        self.assertEqual(code, 1, out)
        self.assertIn("不接管", out)
        self.assertIn("install --force", out)
        self.assertEqual((self.tmp / "AGENTS.md").read_text(encoding="utf-8"), original)
        self.assertFalse((self.tmp / ".agents").exists(), "sync 不得写入任何项目文件")

    def test_install_refuses_foreign_without_force(self):
        (self.tmp / "AGENTS.md").write_text(self.FOREIGN, encoding="utf-8")
        code, out = run_script("install", "--project", str(self.tmp))
        self.assertEqual(code, 1, out)
        self.assertEqual((self.tmp / "AGENTS.md").read_text(encoding="utf-8"), self.FOREIGN)

    def test_install_force_adopts_keeps_section2(self):
        (self.tmp / "AGENTS.md").write_text(self.FOREIGN, encoding="utf-8")
        code, out = run_script("install", "--force", "--project", str(self.tmp))
        self.assertEqual(code, 0, out)
        text = (self.tmp / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("<!-- tsc-managed-contract:v4 -->", text)
        self.assertIn("| 测试 (Test) | pytest |", text)  # 项目 §2 取值保留
        self.assertNotIn("这是项目自己的规则", text)    # 正文已按母版重建

    def test_sync_force_is_rejected(self):
        (self.tmp / "AGENTS.md").write_text(self.FOREIGN, encoding="utf-8")
        code, out = run_script("sync", "--force", "--project", str(self.tmp))
        self.assertEqual(code, 3, out)
        self.assertIn("install --force", out)

    def test_managed_keeps_custom_section2(self):
        code, _ = self.install()
        self.assertEqual(code, 0)
        agents = self.tmp / "AGENTS.md"
        agents.write_text(
            re.sub(r"\| 测试 \(Test\) \|[^\n]*\|", "| 测试 (Test) | pytest -q |",
                   agents.read_text(encoding="utf-8")),
            encoding="utf-8")
        code, out = run_script("sync", "--project", str(self.tmp))
        self.assertEqual(code, 0, out)
        self.assertIn("| 测试 (Test) | pytest -q |", agents.read_text(encoding="utf-8"))

    def test_section2_structure_drift_still_rejected(self):
        code, _ = self.install()
        self.assertEqual(code, 0)
        agents = self.tmp / "AGENTS.md"
        agents.write_text(
            re.sub(r"\| 格式化 \(Format\) \|[^\n]*\|\n", "",
                   agents.read_text(encoding="utf-8")),
            encoding="utf-8")
        code, out = run_script("sync", "--project", str(self.tmp))
        self.assertEqual(code, 1, out)
        self.assertIn("缺少字段", out)

    def test_user_took_over_enforcement_not_overwritten(self):
        code, _ = self.install()
        self.assertEqual(code, 0)
        target = self.tmp / "commitlint.config.js"
        (self.tmp / "package.json").write_text("{}", encoding="utf-8")  # 先变 Node 项目
        code, _ = run_script("sync", "--project", str(self.tmp))
        self.assertEqual(code, 0)
        lines = [ln for ln in target.read_text(encoding="utf-8").splitlines()
                 if "tsc-managed" not in ln]
        target.write_text("\n".join(lines) + "\n// 项目接管\n", encoding="utf-8")
        code, out = run_script("sync", "--project", str(self.tmp))
        self.assertEqual(code, 0, out)
        self.assertIn("内容已被项目改过", out)
        self.assertIn("// 项目接管", target.read_text(encoding="utf-8"))

    def test_section2_drift_writes_nothing(self):
        (self.tmp / "AGENTS.md").write_text(self.FOREIGN.replace(
            "| 已知豁免清单 | 无 | 白名单 |", ""), encoding="utf-8")
        code, out = run_script("sync", "--project", str(self.tmp))
        self.assertEqual(code, 1, out)
        self.assertFalse((self.tmp / ".agents").exists())


class VerifyGateTests(E2EBase):
    def test_all_skip_fails_loud(self):
        code, _ = self.install()
        self.assertEqual(code, 0)
        code, out = run_script("verify", "--project", str(self.tmp))
        self.assertEqual(code, 3, out)
        self.assertIn("假绿", out)
        self.assertNotIn("门禁结论：全绿", out)

    def test_exit_code_passthrough(self):
        code, _ = self.install()
        self.assertEqual(code, 0)
        probe = self.tmp / "gate_probe.py"
        py_exe = sys.executable.replace("\\", "/")
        self.set_project_py(self.tmp, '"%s" gate_probe.py' % py_exe)
        self.adapt_section2(self.tmp, '"%s" gate_probe.py' % py_exe)
        probe.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
        code, out = run_script("verify", "--project", str(self.tmp))
        self.assertEqual(code, 0, out)
        probe.write_text("import sys\nsys.exit(7)\n", encoding="utf-8")
        code, out = run_script("verify", "--project", str(self.tmp))
        self.assertEqual(code, 7, out)
        self.assertIn("退出码：7", out)

    def test_verify_timeout_kills_and_returns_124(self):
        """P1-05：卡死的门禁命令被超时终止，绝不无限等待。"""
        code, _ = self.install()
        self.assertEqual(code, 0)
        self.set_project_py(self.tmp, SLOW_CMD)
        self.adapt_section2(self.tmp, SLOW_CMD)
        start = time.monotonic()
        code, out = run_script("verify", "--timeout", "1", "--project", str(self.tmp))
        elapsed = time.monotonic() - start
        self.assertEqual(code, 124, out)
        self.assertLess(elapsed, 30, "超时后必须很快返回")
        self.assertIn("超时", out)
        self.assertIn("124", out)

    def test_per_step_timeout_override(self):
        code, _ = self.install()
        self.assertEqual(code, 0)
        (self.tmp / ".agents" / "project.py").write_text(
            'FMT_CHECK_CMD = None\nLINT_CMD = None\nTEST_CMD = %r\nBUILD_CMD = None\n'
            'GATE_TIMEOUTS = {"TEST_CMD": 1}\n' % SLOW_CMD,
            encoding="utf-8")
        self.adapt_section2(self.tmp, SLOW_CMD)
        start = time.monotonic()
        code, out = run_script("verify", "--project", str(self.tmp))
        elapsed = time.monotonic() - start
        self.assertEqual(code, 124, out)
        self.assertLess(elapsed, 30)

    def test_check_config_flags_mismatch_and_green(self):
        code, _ = self.install()
        self.assertEqual(code, 0)
        code, out = run_script("check-config", "--project", str(self.tmp))
        self.assertEqual(code, 1, out)  # 新装未适配 → 不一致
        self.set_project_py(self.tmp, "echo t-ok")
        self.adapt_section2(self.tmp, "echo t-ok")
        code, out = run_script("check-config", "--project", str(self.tmp))
        self.assertEqual(code, 0, out)

    def test_gate_inline_shell_matches_local(self):
        """CI 内联壳与本地 tsc.py 同判定：假绿 3 / 不一致 1 / 全绿 0。"""
        code, _ = self.install()
        self.assertEqual(code, 0)

        def inline():
            return subprocess.run([sys.executable, "-c", gate_inline_source()],
                                  cwd=str(self.tmp), capture_output=True)

        proc = inline()
        self.assertEqual(proc.returncode, 3)  # 全未配置 = 假绿
        self.set_project_py(self.tmp, "echo from-project-py")
        self.adapt_section2(self.tmp, "echo from-section2")
        proc = inline()
        self.assertEqual(proc.returncode, 1)  # §2 与 project.py 不一致
        self.set_project_py(self.tmp, "echo gate-ok")
        self.adapt_section2(self.tmp, "echo gate-ok")
        proc = inline()
        combined = (proc.stdout + proc.stderr).decode("utf-8", errors="replace")
        self.assertEqual(proc.returncode, 0, combined)
        self.assertIn("同源校验", combined)
        self.assertIn("gate-ok", combined)


class RollbackTests(E2EBase):
    def test_rollback_restores_previous_state(self):
        code, out = self.install()
        self.assertEqual(code, 0, out)
        # §2 定制 + 托管区域被手改（sync 必须只重建托管区域、保留 §2 定制）
        agents = self.tmp / "AGENTS.md"
        agents.write_text(
            re.sub(r"\| 测试 \(Test\) \|[^\n]*\|", "| 测试 (Test) | pytest -q |",
                   agents.read_text(encoding="utf-8")),
            encoding="utf-8")
        tampered = agents.read_text(encoding="utf-8").replace(
            "**未验证不交付**", "（此处被手改）")
        self.assertNotEqual(tampered, agents.read_text(encoding="utf-8"))
        agents.write_text(tampered, encoding="utf-8")
        # sync 重建托管区域
        code, out = run_script("sync", "--project", str(self.tmp))
        self.assertEqual(code, 0, out)
        synced = agents.read_text(encoding="utf-8")
        self.assertIn("**未验证不交付**", synced)
        self.assertIn("| 测试 (Test) | pytest -q |", synced)  # §2 定制保留
        # rollback 恢复 sync 前原状（含手改与定制）
        code, out = run_script("rollback", "--project", str(self.tmp))
        self.assertEqual(code, 0, out)
        self.assertEqual(agents.read_text(encoding="utf-8"), tampered,
                         "rollback 后应恢复到 sync 前的项目状态")
        self.assertFalse((self.tmp / ".agents" / ".tsc-backup").exists(),
                         "回滚后备份清单应清理")

    def test_rollback_removes_files_created_by_last_apply(self):
        # 第一次 install 前无契约 → rollback 应删掉 install 新建的文件
        code, _ = self.install()
        self.assertEqual(code, 0)
        code, out = run_script("rollback", "--project", str(self.tmp))
        self.assertEqual(code, 0, out)
        for rel in ("AGENTS.md", ".agents/project.py", ".agents/VERSION",
                    ".pre-commit-config.yaml", ".agents/structure_guard.py"):
            self.assertFalse((self.tmp / rel).exists(), "应删除上次新建的 %s" % rel)

    def test_rollback_without_backup_fails_3(self):
        code, out = run_script("rollback", "--project", str(self.tmp))
        self.assertEqual(code, 3, out)
        self.assertIn("没有可回滚的记录", out)


class DoctorStatusTests(E2EBase):
    def test_doctor_fresh_install_not_ready_then_ready_after_adapt(self):
        code, out = self.install()
        self.assertEqual(code, 0, out)
        code, out = run_script("doctor", "--project", str(self.tmp))
        self.assertEqual(code, 3, out)
        self.assertIn("not-ready", out)
        self.assertIn("[自动填充]", out)
        self.set_project_py(self.tmp, "echo t-ok")
        self.adapt_section2(self.tmp, "echo t-ok")
        code, out = run_script("doctor", "--project", str(self.tmp))
        self.assertEqual(code, 0, out)
        self.assertIn("ready", out)

    def test_doctor_flags_foreign_agents(self):
        (self.tmp / "AGENTS.md").write_text("# 外部规范\n\n无 §2\n", encoding="utf-8")
        code, out = run_script("doctor", "--project", str(self.tmp))
        self.assertEqual(code, 3, out)
        self.assertIn("外部", out)

    def test_doctor_non_node_reports_no_npm(self):
        code, out = run_script("doctor", "--project", str(self.tmp))
        self.assertIn("不部署 commitlint", out)

    def test_doctor_on_master_repo_does_not_flag_enforcement_missing(self):
        """A-03：母版自举按设计不铺生效件，doctor 不得把这说成"执法包缺失"。

        修复前母版自检永远弹 4 条黄标（gate.yml / pre-commit / 两份落盘检查器），
        把"设计如此"报成"缺文件"——噪音会掩盖真问题。
        """
        code, out = run_script("sync", "--project", str(REPO))  # 自举生成 .agents/VERSION 等
        self.assertEqual(code, 0, out)
        code, out = run_script("doctor", "--project", str(REPO))
        self.assertEqual(code, 0, out)
        self.assertIn("按设计不铺生效件", out)
        self.assertNotIn("缺失", out)

    def test_status_json_is_machine_readable(self):
        code, _ = self.install()
        self.assertEqual(code, 0)
        code, out = run_script("status", "--json", "--project", str(self.tmp))
        self.assertEqual(code, 0, out)
        data = json.loads(out)
        self.assertEqual(data["ownership"], "managed")
        self.assertEqual(data["contract_version"], "5.0.0")
        self.assertTrue(data["installed"])

    def test_version_flag(self):
        code, out = run_script("--version")
        self.assertEqual(code, 0, out)
        self.assertEqual(out.strip(), "5.0.0")


if __name__ == "__main__":
    unittest.main()
