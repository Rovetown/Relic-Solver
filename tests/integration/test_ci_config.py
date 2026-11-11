import json
import re
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
JUSTFILE = REPO_ROOT / "justfile"


def _pytest_addopts() -> str:
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        config = tomllib.load(fh)
    return str(config["tool"]["pytest"]["ini_options"]["addopts"])


def _benchmark_invocations() -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for path in [*sorted(WORKFLOWS.glob("*.yml")), JUSTFILE]:
        for line in path.read_text().splitlines():
            if "pytest" in line and "--benchmark-only" in line:
                found.append((path.name, line.strip()))
    return found


class TestCoverageGate:
    def test_gate_is_configured(self) -> None:
        assert "--cov-fail-under" in _pytest_addopts()

    def test_the_web_layer_is_measured(self) -> None:
        assert "--cov=app" in _pytest_addopts()

    def test_the_solver_is_measured(self) -> None:
        assert "--cov=relic_solver" in _pytest_addopts()


class TestBenchmarkRunsSkipCoverage:
    def test_at_least_one_invocation_exists(self) -> None:
        assert _benchmark_invocations()

    @pytest.mark.parametrize("source,line", _benchmark_invocations())
    def test_invocation_disables_coverage(self, source: str, line: str) -> None:
        assert "--no-cov" in line, f"{source}: {line}"


class TestDependencyAudit:
    def _pr_workflow(self) -> str:
        return (WORKFLOWS / "ci-pr.yml").read_text()

    def test_audit_job_exists(self) -> None:
        assert re.search(r"^\s{2}audit:", self._pr_workflow(), re.MULTILINE)

    def test_python_dependencies_are_audited(self) -> None:
        assert "pip-audit" in self._pr_workflow()

    def test_js_dependencies_are_audited(self) -> None:
        assert "npm audit" in self._pr_workflow()

    def test_audit_covers_runtime_dependencies_only(self) -> None:
        assert "uv sync --frozen --no-dev" in self._pr_workflow()

    def test_audit_is_not_advisory_only(self) -> None:
        workflow = self._pr_workflow()
        audit_section = workflow[workflow.index("  audit:") :]
        assert "continue-on-error" not in audit_section


class TestImageIsBuiltInCi:
    def test_a_workflow_builds_the_image(self) -> None:
        built = any(
            "docker build" in path.read_text()
            for path in WORKFLOWS.glob("*.yml")
        )
        assert built

    def test_the_dockerfile_is_linted(self) -> None:
        linted = any(
            "hadolint" in path.read_text() for path in WORKFLOWS.glob("*.yml")
        )
        assert linted

    def test_the_image_is_scanned(self) -> None:
        scanned = any(
            "trivy" in path.read_text().lower() for path in WORKFLOWS.glob("*.yml")
        )
        assert scanned


class TestShippedJavaScriptIsLinted:
    def test_a_linter_is_configured(self) -> None:
        config = REPO_ROOT / ".oxlintrc.json"
        assert config.is_file()

    def test_it_runs_as_a_pre_commit_hook(self) -> None:
        hooks = (REPO_ROOT / ".pre-commit-config.yaml").read_text()
        assert "id: oxlint" in hooks

    def test_warnings_are_not_tolerated(self) -> None:
        hooks = (REPO_ROOT / ".pre-commit-config.yaml").read_text()
        oxlint_block = hooks[hooks.index("id: oxlint") :]
        assert "--deny-warnings" in oxlint_block[:300]

    @pytest.mark.parametrize("workflow", ["ci-pr.yml", "ci-main.yml"])
    def test_ci_installs_a_pinned_version(self, workflow: str) -> None:
        text = (WORKFLOWS / workflow).read_text()
        assert re.search(r"OXLINT_VERSION: '\d+\.\d+\.\d+'", text)

    def test_no_undef_is_enabled(self) -> None:
        config = json.loads((REPO_ROOT / ".oxlintrc.json").read_text())
        assert config["rules"]["no-undef"] == "error"

    @pytest.mark.parametrize("workflow", ["ci-pr.yml", "ci-main.yml"])
    def test_it_runs_in_ci(self, workflow: str) -> None:
        assert "pre-commit run --all-files" in (WORKFLOWS / workflow).read_text()


class TestRedisServiceInCi:
    @pytest.mark.parametrize("workflow", ["ci-pr.yml", "ci-main.yml"])
    def test_workflow_provides_redis(self, workflow: str) -> None:
        text = (WORKFLOWS / workflow).read_text()
        assert "redis:8-alpine" in text

    @pytest.mark.parametrize("workflow", ["ci-pr.yml", "ci-main.yml"])
    def test_workflow_points_the_app_at_it(self, workflow: str) -> None:
        text = (WORKFLOWS / workflow).read_text()
        assert "REDIS_URL" in text


class TestWorkflowsDeselectTheBrowserSuite:
    def _pytest_marker_invocations(self) -> list[tuple[str, str]]:
        found: list[tuple[str, str]] = []
        for path in sorted(WORKFLOWS.glob("*.yml")):
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if "pytest" in stripped and re.search(r'-m\s+"', stripped):
                    found.append((path.name, stripped))
        return found

    def test_addopts_still_deselects_the_browser_suite(self) -> None:
        assert "not browser" in _pytest_addopts()

    def test_every_workflow_marker_keeps_the_browser_suite_out(self) -> None:
        invocations = self._pytest_marker_invocations()
        assert invocations, "no workflow pytest invocation passes -m; test is stale"

        offenders = [
            (name, line)
            for name, line in invocations
            if "--benchmark-only" not in line and "not browser" not in line
        ]
        assert not offenders, (
            "these workflow pytest calls override addopts without excluding the "
            f"browser suite: {offenders}"
        )
