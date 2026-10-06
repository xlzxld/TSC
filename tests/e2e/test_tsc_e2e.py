# -*- coding: utf-8 -*-
"""tsc.py 端到端回归（子进程跑真 CLI）。

规格 §10 场景对照：
升级：旧版本 → 新版本裸 sync 必升级；.source 指向旧/失效路径不阻塞、不被采信；
      非 git 安装副本提示走宿主更新。
安全边界：无 marker 的外部 AGENTS.md 不被 sync/install 接管；--force 显式接管；
      有 marker 只更新托管内容；§2 结构变化仍拒绝自动合并；项目接管的执法包不覆盖；
      外部 AGENTS.md + 恰好存在的 .agents/VERSION 仍按 foreign 处理（双特征）。
事务：backup 失败 / 写入失败自动恢复原状；migration-only sync 也有回滚记录；
      rollback 只恢复最近一次成功事务；manifest 路径非法整体拒绝。
门禁：verify 超时杀进程组返回 124；退出码透传；假绿 rc=3；CI 内联壳与本地同判定
      （含 AST 配置解析同源）；恶意 project.py 绝不执行。
上游：残缺上游（缺必要产物 / 版本格式非法）拒绝 install/sync，零项目写盘。

测试隔离：所有测试只在各自临时目录里跑；涉及"母版仓库"的场景（自举/doctor）
用整仓临时副本（copytree）承载，绝不写真实仓库——完整 discovery 顺序无关。
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
CURRENT_VERSION = (SKILL / "VERSION").read_text(encoding="utf-8").strip()

# 跨平台门禁夹具：`true` / `sleep` 是 POSIX 专属，Windows 上没有（A-02）。
QUICK_CMD = '"%s" -c "pass"' % sys.executable
SLOW_CMD = '"%s" -c "import time;time.sleep(60)"' % sys.executable

# 子进程必须有界：任何环节卡死都以"测试失败"暴露，而不是挂住整个 discovery。
SUBPROC_TIMEOUT_S = 180


def run_script(*args, cwd=None):
    """以子进程跑 tsc.py，返回 (退出码, 合并后的 stdout+stderr)。"""
    try:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT)] + list(args),
            capture_output=True, cwd=str(cwd) if cwd else None,
            timeout=SUBPROC_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        raise AssertionError("tsc.py %s 超过 %ss 未退出（疑似进程泄漏）"
                             % (" ".join(args), SUBPROC_TIMEOUT_S))
    out = (proc.stdout + proc.stderr).decode("utf-8", errors="replace")
    return proc.returncode, out


def make_repo_replica(dest):
    """整仓临时副本：承载"母版仓库"场景（自举 sync / doctor），与真实仓库完全隔离。

    附带真实 .agents/project.py（§2 同源的命令源）；VERSION/.source 由副本自己的
    sync 重写，不继承本机 provenance。
    """
    shutil.copytree(
        REPO, dest,
        ignore=shutil.ignore_patterns(".git", "__pycache__", ".agents", ".tsc-tmp"),
    )
    (dest / ".agents").mkdir(exist_ok=True)
    shutil.copyfile(REPO / ".agents" / "project.py", dest / ".agents" / "project.py")
    return dest


def run_replica_script(replica, *args):
    """用副本自己的 tsc.py 跑命令——upstream_root() 落在副本内，自举判定才成立。"""
    try:
        proc = subprocess.run(
            [sys.executable, str(replica / "skills" / "tsc" / "scripts" / "tsc.py")] + list(args),
            capture_output=True, timeout=SUBPROC_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        raise AssertionError("replica tsc.py %s 超过 %ss 未退出" % (" ".join(args), SUBPROC_TIMEOUT_S))
    return proc.returncode, (proc.stdout + proc.stderr).decode("utf-8", errors="replace")


def make_full_upstream(dest, version=None, template_text=None):
    """构造一个"完整"的自定义上游（v5.2.0 起残缺上游一票否决，夹具必须齐备）。"""
    shutil.copytree(SKILL, dest, ignore=shutil.ignore_patterns("__pycache__"))
    if version is not None:
        (dest / "VERSION").write_text(version + "\n", encoding="utf-8")
    if template_text is not None:
        (dest / "templates" / "AGENTS.md").write_text(template_text, encoding="utf-8")
    return dest


def make_dir_link(link, target):
    """建目录链接：优先真 symlink，Windows 无特权时退回 junction；都不行 None。"""
    try:
        os.symlink(str(target), str(link), target_is_directory=True)
        return True
    except (OSError, NotImplementedError, AttributeError):
        pass
    try:
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
        return True
    except (OSError, ImportError):
        return None


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
        self.assertEqual(version, CURRENT_VERSION)

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
        self.assertEqual(record["version"], CURRENT_VERSION)
        self.assertIn("installed_at", record)

    def test_sync_same_state_is_noop(self):
        code, _ = self.install()
        self.assertEqual(code, 0)
        code, out = run_script("sync", "--project", str(self.tmp))
        self.assertEqual(code, 0, out)
        self.assertIn("已是最新", out)

    def test_self_repo_sync_keeps_agents_md(self):
        """母版自举（临时副本承载，不写真实仓库）：对自己 sync 不铺执法包、不动根 AGENTS.md。"""
        replica = make_repo_replica(self.tmp / "master-replica")
        before = (replica / "AGENTS.md").read_bytes()
        code, out = run_replica_script(replica, "sync", "--project", str(replica))
        self.assertEqual(code, 0, out)
        self.assertEqual((replica / "AGENTS.md").read_bytes(), before,
                         "自举 sync 不得改动根 AGENTS.md")
        self.assertFalse((replica / ".pre-commit-config.yaml").exists(),
                         "母版自举不得把执法包铺进仓库根")
        # 再 sync 一次：无漂移
        code, out = run_replica_script(replica, "sync", "--project", str(replica))
        self.assertEqual(code, 0, out)
        self.assertIn("已是最新", out)


class UpgradeTests(E2EBase):
    """规格 §10 升级场景 + P1-01 核心回归。"""

    def _make_v3_project(self):
        """模拟 v3.3.2 旧版安装的项目：无 marker、.source 指向一个已消失的旧技能目录。"""
        code, out = self.install()
        self.assertEqual(code, 0, out)
        agents = self.tmp / "AGENTS.md"
        text = agents.read_text(encoding="utf-8").replace("<!-- tsc-managed-contract:v4 -->\n\n", "")
        text = re.sub(r">\s*\*\*版本\s+v[0-9.]+\*\*", "> **版本 v3.3.2**", text)
        agents.write_text(text, encoding="utf-8")
        (self.tmp / ".agents" / "VERSION").write_text("3.3.2\n", encoding="utf-8")
        (self.tmp / ".agents" / ".source").write_text(
            "/nonexistent/old/skills/tsc\n", encoding="utf-8")

    def test_bare_sync_upgrades_legacy_project_despite_stale_source(self):
        """P1-01：旧版项目裸 sync 必须升级到当前本体；.source 旧路径不被采信、不阻塞。"""
        self._make_v3_project()
        code, out = run_script("sync", "--project", str(self.tmp))
        self.assertEqual(code, 0, out)
        self.assertIn("3.3.2 → %s" % CURRENT_VERSION, out)
        agents = (self.tmp / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("<!-- tsc-managed-contract:v4 -->", agents)
        self.assertEqual((self.tmp / ".agents" / "VERSION").read_text().strip(), CURRENT_VERSION)
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
            (self.tmp / ".agents" / "VERSION").read_text().strip(), CURRENT_VERSION,
            "裸 sync 后版本必须是当前本体的，不是 .source 指向的旧上游")

    def test_explicit_source_used_for_one_sync_then_repoints_provenance(self):
        # 上游夹具必须完整（v5.2.0 起残缺上游在入口即被拒）
        other = make_full_upstream(self.tmp / "up", version="9.9.9")
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
        self.assertEqual((self.tmp / ".agents" / "VERSION").read_text().strip(), CURRENT_VERSION)

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

    def test_gate_inline_shell_survives_non_utf8_console(self):
        """CI 在 Windows 上抓到的真实缺陷：内联壳没强制 UTF-8，cp1252 下中文 print 崩掉。

        退出码因此从 1（§2 占位 = 未适配，A-04② 起与本地 check-config 同口径）
        变成崩溃码——两套壳的判定就此漂移，而本地 tsc.py 一直有这层兜底。
        用 PYTHONIOENCODING=cp1252 强制复现。
        """
        code, _ = self.install()
        self.assertEqual(code, 0)
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "cp1252"
        proc = subprocess.run([sys.executable, "-c", gate_inline_source()],
                              cwd=str(self.tmp), capture_output=True, env=env)
        self.assertEqual(proc.returncode, 1,
                         (proc.stdout + proc.stderr).decode("utf-8", "replace")[-600:])

    def test_gate_inline_shell_matches_local(self):
        """CI 内联壳与本地 tsc.py 同判定（A-04② 起含 §2 占位场景）：
        占位 1 / 不一致 1 / 全绿 0。"""
        code, _ = self.install()
        self.assertEqual(code, 0)

        def inline():
            return subprocess.run([sys.executable, "-c", gate_inline_source()],
                                  cwd=str(self.tmp), capture_output=True)

        proc = inline()
        combined = (proc.stdout + proc.stderr).decode("utf-8", errors="replace")
        self.assertEqual(proc.returncode, 1, combined)  # §2 占位 = 未适配（与 check-config 同口径）
        self.assertIn("[自动填充]", combined)
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
        把"设计如此"报成"缺文件"——噪音会掩盖真问题。用整仓临时副本跑，
        不写真实仓库（测试隔离）。
        """
        replica = make_repo_replica(self.tmp / "master-replica")
        code, out = run_replica_script(replica, "sync", "--project", str(replica))  # 自举
        self.assertEqual(code, 0, out)
        code, out = run_replica_script(replica, "doctor", "--project", str(replica))
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
        self.assertEqual(data["contract_version"], CURRENT_VERSION)
        self.assertTrue(data["installed"])

    def test_version_flag(self):
        code, out = run_script("--version")
        self.assertEqual(code, 0, out)
        self.assertEqual(out.strip(), CURRENT_VERSION)


class TransactionAdversarialTests(E2EBase):
    """事务失败安全：任一步失败必须恢复到事务开始前状态，绝不留半成品。"""

    def test_backup_failure_aborts_before_any_project_write(self):
        """备份落盘失败（.tsc-backup 被同名文件占用）→ 写盘前整体终止。"""
        (self.tmp / ".agents").mkdir()
        (self.tmp / ".agents" / ".tsc-backup").write_text("not a dir", encoding="utf-8")
        code, out = self.install()
        self.assertEqual(code, 2, out)
        self.assertFalse((self.tmp / "AGENTS.md").exists(), "backup 失败不得写任何项目文件")
        self.assertFalse((self.tmp / ".pre-commit-config.yaml").exists())
        self.assertIn("事务失败", out)

    def test_mid_transaction_write_failure_rolls_back_everything(self):
        """.github 被同名文件占用 → gate.yml 父目录创建失败 → 已写入内容全部回滚。"""
        (self.tmp / ".github").write_text("not a dir", encoding="utf-8")
        code, out = self.install()
        self.assertEqual(code, 2, out)
        self.assertFalse((self.tmp / "AGENTS.md").exists(), "回滚后不得留下任何写入")
        self.assertFalse((self.tmp / ".pre-commit-config.yaml").exists())
        self.assertFalse((self.tmp / ".agents").exists(), "事务新建的目录必须一并清掉")

    def test_migration_only_sync_has_fresh_rollback_record(self):
        """migration-only sync：迁移进同一事务，且拥有对应的最新回滚记录。"""
        code, out = self.install()
        self.assertEqual(code, 0, out)
        code, out = run_script("sync", "--project", str(self.tmp))
        self.assertEqual(code, 0, out)
        self.assertIn("已是最新", out)  # 前置：除迁移外无任何漂移
        legacy_dir = self.tmp / "test"
        legacy_dir.mkdir()
        (legacy_dir / "EVAL-SET.md").write_text("x\n", encoding="utf-8")
        (legacy_dir / "TEST-MANUAL.md").write_text("x\n", encoding="utf-8")
        code, out = run_script("sync", "--project", str(self.tmp))
        self.assertEqual(code, 0, out)
        self.assertIn("已迁移", out)
        self.assertTrue((self.tmp / ".agents" / "test" / "EVAL-SET.md").is_file())
        self.assertFalse(legacy_dir.exists())
        # rollback 把迁移搬回原位（迁移记录进了同一清单）
        code, out = run_script("rollback", "--project", str(self.tmp))
        self.assertEqual(code, 0, out)
        self.assertTrue((legacy_dir / "EVAL-SET.md").is_file(), "rollback 应把迁移搬回原位")
        self.assertFalse((self.tmp / ".agents" / "test").exists())
        self.assertTrue((self.tmp / "AGENTS.md").is_file(), "其余文件不受影响")

    def test_rollback_restores_only_the_last_successful_transaction(self):
        """连续 install/sync/rollback：只恢复最近一次成功事务，不误回退更早状态。"""
        code, _ = self.install()
        self.assertEqual(code, 0)
        agents = self.tmp / "AGENTS.md"

        def tamper(tag):
            text = agents.read_text(encoding="utf-8").replace("**未验证不交付**", "（手改%s）" % tag)
            self.assertIn("（手改%s）" % tag, text)  # 前置：确实改到了
            agents.write_text(text, encoding="utf-8")

        tamper("A")
        code, _ = run_script("sync", "--project", str(self.tmp))
        self.assertEqual(code, 0)
        tamper("B")
        code, _ = run_script("sync", "--project", str(self.tmp))
        self.assertEqual(code, 0)
        code, out = run_script("rollback", "--project", str(self.tmp))
        self.assertEqual(code, 0, out)
        restored = agents.read_text(encoding="utf-8")
        self.assertIn("（手改B）", restored, "rollback 恢复最近一次事务前的状态")
        self.assertNotIn("（手改A）", restored, "不得误回退到更早事务")
        # 回滚后清单已清空：再 rollback 报 3
        code, out = run_script("rollback", "--project", str(self.tmp))
        self.assertEqual(code, 3, out)
        self.assertIn("没有可回滚的记录", out)


class ConfigSafetyE2ETests(E2EBase):
    """配置安全：doctor / check-config / verify 绝不执行 project.py。"""

    def test_malicious_project_py_never_executed(self):
        code, _ = self.install()
        self.assertEqual(code, 0)
        marker = self.tmp / "pwned.txt"
        marker_rel = marker.as_posix()
        (self.tmp / ".agents" / "project.py").write_text(
            'import os\n'
            'os.system("echo pwned > \\"%s\\"")\n'
            'TEST_CMD = "echo ok"\n' % marker_rel,
            encoding="utf-8")
        for command in ("verify", "check-config", "doctor"):
            code, out = run_script(command, "--project", str(self.tmp))
            self.assertEqual(code, 3, "%s 应拒绝恶意配置：%s" % (command, out))
        self.assertFalse(marker.exists(), "AST 解析路径绝不能执行 project.py 中的代码")

    def test_call_payload_project_py_rejected(self):
        code, _ = self.install()
        self.assertEqual(code, 0)
        (self.tmp / ".agents" / "project.py").write_text(
            'TEST_CMD = __import__("os").getenv("PATH")\n', encoding="utf-8")
        code, out = run_script("check-config", "--project", str(self.tmp))
        self.assertEqual(code, 3, out)
        self.assertIn("禁止函数调用", out)


class OwnershipAdversarialTests(E2EBase):
    """所有权收紧：外部 AGENTS.md + 恰好存在的 .agents/VERSION 不被自动接管。"""

    FOREIGN_TEXT = OwnershipBoundaryTests.FOREIGN

    def test_foreign_agents_with_stray_version_file_stays_foreign(self):
        (self.tmp / "AGENTS.md").write_text(self.FOREIGN_TEXT, encoding="utf-8")
        (self.tmp / ".agents").mkdir()
        (self.tmp / ".agents" / "VERSION").write_text("5.0.0\n", encoding="utf-8")
        code, out = run_script("sync", "--project", str(self.tmp))
        self.assertEqual(code, 1, out)
        self.assertIn("不接管", out)
        self.assertEqual((self.tmp / "AGENTS.md").read_text(encoding="utf-8"), self.FOREIGN_TEXT)
        # 除预置内容外没有任何新写入
        self.assertEqual(sorted(p.name for p in (self.tmp / ".agents").iterdir()), ["VERSION"])

    def test_foreign_agents_with_version_and_source_is_legacy_upgrade(self):
        """凑齐两个 TSC 特征（VERSION + .source）才是合法的 v3.x 升级路径。"""
        (self.tmp / "AGENTS.md").write_text(self.FOREIGN_TEXT, encoding="utf-8")
        (self.tmp / ".agents").mkdir()
        (self.tmp / ".agents" / "VERSION").write_text("3.3.2\n", encoding="utf-8")
        (self.tmp / ".agents" / ".source").write_text("/old/skill\n", encoding="utf-8")
        code, out = run_script("sync", "--project", str(self.tmp))
        self.assertEqual(code, 0, out)
        self.assertIn("<!-- tsc-managed-contract:v4 -->",
                      (self.tmp / "AGENTS.md").read_text(encoding="utf-8"))


class UpstreamAdversarialTests(E2EBase):
    """残缺上游：缺任一必要产物 / 版本格式非法 => 拒绝，零项目写盘。"""

    def test_missing_required_artifact_blocks_install_and_sync(self):
        broken = make_full_upstream(self.tmp / "broken-up")
        (broken / "references" / "BOOTSTRAP.md").unlink()
        for command in ("install", "sync"):
            code, out = run_script(command, "--source", str(broken), "--project", str(self.tmp))
            self.assertEqual(code, 3, out)
            self.assertIn("BOOTSTRAP.md", out)
        self.assertFalse((self.tmp / "AGENTS.md").exists(), "上游校验失败不得写项目")
        self.assertFalse((self.tmp / ".agents").exists())

    def test_bad_version_format_blocks_install(self):
        broken = make_full_upstream(self.tmp / "badver-up", version="not-a-version")
        code, out = run_script("install", "--source", str(broken), "--project", str(self.tmp))
        self.assertEqual(code, 3, out)
        self.assertIn("版本格式非法", out)
        self.assertFalse((self.tmp / "AGENTS.md").exists())


class BranchRenderingE2ETests(E2EBase):
    """CI 分支名渲染：合法但含特殊字符的分支名必须产出合法 YAML flow 序列。"""

    def _set_trunk(self, proj, branch):
        agents = Path(proj) / "AGENTS.md"
        text = agents.read_text(encoding="utf-8")
        text = re.sub(r"\| 主干分支 \|[^\n]*\|", "| 主干分支 | %s | ✅ 禁止直推 |" % branch,
                      text, count=1)
        agents.write_text(text, encoding="utf-8")

    @staticmethod
    def _expected(branch):
        if branch and branch[0].isalnum() and all(
                c.isalnum() or c in "._-" for c in branch):
            return "branches: [%s]" % branch
        return "branches: ['%s']" % branch.replace("'", "''")

    def test_special_branch_names_render_quoted_and_idempotent(self):
        for branch in ("release/1,2", "fix]ing", "feature #1", "sp ace", "a{b}"):
            with self.subTest(branch=branch):
                proj = Path(tempfile.mkdtemp(prefix="tsc-br-"))
                self.addCleanup(shutil.rmtree, proj, True)
                code, out = self.install(proj)
                self.assertEqual(code, 0, out)
                self._set_trunk(proj, branch)
                code, out = run_script("sync", "--project", str(proj))
                self.assertEqual(code, 0, out)
                gate = (proj / ".github" / "workflows" / "gate.yml").read_text(encoding="utf-8")
                self.assertIn(self._expected(branch), gate)
                self.assertNotIn("branches: [%s]" % branch, gate)  # 裸插值即坏 YAML
                # 再次 sync：渲染确定性（debranch 可逆 → 无漂移）
                code, out = run_script("sync", "--project", str(proj))
                self.assertEqual(code, 0, out)
                self.assertIn("已是最新", out)


class SymlinkEscapeE2ETests(E2EBase):
    """symlink/junction 逃逸：受管理路径被链接劫持时拒绝写入。"""

    def test_agents_dir_link_escape_refused(self):
        outside = Path(tempfile.mkdtemp(prefix="tsc-outside-"))
        self.addCleanup(shutil.rmtree, outside, True)
        if not make_dir_link(self.tmp / ".agents", outside):
            self.skipTest("本机既不能建 symlink 也不能建 junction，跳过")
        code, out = self.install()
        self.assertNotEqual(code, 0, out)
        self.assertIn("不安全", out)
        self.assertFalse((self.tmp / "AGENTS.md").exists())
        self.assertEqual(list(outside.iterdir()), [], "项目外的目录绝不被写入")


class AuditRoundE2ETests(E2EBase):
    """收官体检 A-01~A-11 的端到端回归（与 unit 层各锁一半）。"""

    def test_update_on_host_project_repo_refuses_pull(self):
        """A-09：技能被装进宿主项目仓库内（未跟踪）→ update 绝不 pull 宿主仓库。"""
        host = self.tmp / "host-project"
        host.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=str(host), check=True,
                       capture_output=True)
        vendored = host / "tools" / "tsc"
        shutil.copytree(SKILL, vendored, ignore=shutil.ignore_patterns("__pycache__"))
        proc = subprocess.run(
            [sys.executable, str(vendored / "scripts" / "tsc.py"), "update"],
            capture_output=True, timeout=SUBPROC_TIMEOUT_S)
        out = (proc.stdout + proc.stderr).decode("utf-8", errors="replace")
        self.assertEqual(proc.returncode, 3, out)
        self.assertIn("不 pull 宿主项目", out)
        self.assertIn("收录", out)

    def test_sync_uptodate_reports_blocked_migration(self):
        """A-10：无漂移早退也必须报告迁移受阻，不能吞掉。"""
        code, out = self.install()
        self.assertEqual(code, 0, out)
        code, out = run_script("sync", "--project", str(self.tmp))
        self.assertEqual(code, 0, out)
        self.assertIn("已是最新", out)
        (self.tmp / "AUDIT-SPEC.md").write_text("# old\n", encoding="utf-8")
        (self.tmp / ".agents" / "AUDIT-SPEC.md").write_text("# conflict\n", encoding="utf-8")
        code, out = run_script("sync", "--project", str(self.tmp))
        self.assertEqual(code, 0, out)
        self.assertIn("已是最新", out)
        self.assertIn("无法自动迁移", out, "早退分支不得吞掉迁移受阻信息")
        self.assertIn("AUDIT-SPEC.md", out)

    def test_install_hints_generated_artifacts_gitignore(self):
        """A-11：install 必须提示 .agents/VERSION / .source 是部署生成物。"""
        code, out = self.install()
        self.assertEqual(code, 0, out)
        self.assertIn("部署生成物", out)
        self.assertIn(".gitignore", out)

    def test_rollback_dry_run_is_rejected_and_keeps_state(self):
        """A-03：rollback --dry-run 拒绝执行，项目与清单原样。"""
        code, _ = self.install()
        self.assertEqual(code, 0)
        agents_before = (self.tmp / "AGENTS.md").read_bytes()
        code, out = run_script("rollback", "--dry-run", "--project", str(self.tmp))
        self.assertEqual(code, 3, out)
        self.assertIn("--dry-run", out)
        self.assertEqual((self.tmp / "AGENTS.md").read_bytes(), agents_before)
        self.assertTrue((self.tmp / ".agents" / ".tsc-backup" / "manifest.json").is_file())
        # 真回滚仍可用
        code, out = run_script("rollback", "--project", str(self.tmp))
        self.assertEqual(code, 0, out)

    def test_rollback_blocked_keeps_manifest_for_retry(self):
        """A-02：还原受阻 → rc=2 且清单保留，用户还能处理后再试。"""
        code, _ = self.install()
        self.assertEqual(code, 0)
        agents = self.tmp / "AGENTS.md"
        agents.write_text(agents.read_text(encoding="utf-8") + "\n<!-- tampered -->\n",
                          encoding="utf-8")
        code, out = run_script("sync", "--project", str(self.tmp))  # AGENTS.md 记为 modify
        self.assertEqual(code, 0, out)
        agents.unlink()   # 目标位置腾空后换成目录 → modify 还原必失败
        agents.mkdir()
        code, out = run_script("rollback", "--project", str(self.tmp))
        self.assertEqual(code, 2, out)
        self.assertIn("回滚未彻底", out)
        self.assertIn("已保留", out)
        self.assertTrue((self.tmp / ".agents" / ".tsc-backup" / "manifest.json").is_file())


    def test_gate_inline_shell_rejects_non_string_command(self):
        """最终审查 F-01：CI 内联壳与本地 verify 同口径——非法配置类型干净 rc=3，不裸崩。

        §2 里登记同一字面量让同源校验先通过，才能证明类型防线真的接住了。"""
        code, out = self.install()
        self.assertEqual(code, 0)
        literal = "['echo', 'hi']"
        (self.tmp / ".agents" / "project.py").write_text(
            'FMT_CHECK_CMD = None\nLINT_CMD = None\nTEST_CMD = %s\nBUILD_CMD = None\n' % literal,
            encoding="utf-8")
        self.adapt_section2(self.tmp, literal)
        proc = subprocess.run([sys.executable, "-c", gate_inline_source()],
                              cwd=str(self.tmp), capture_output=True)
        combined = (proc.stdout + proc.stderr).decode("utf-8", errors="replace")
        self.assertEqual(proc.returncode, 3, combined)
        self.assertIn("必须是字符串", combined)
        self.assertNotIn("Traceback", combined)


if __name__ == "__main__":
    unittest.main()
