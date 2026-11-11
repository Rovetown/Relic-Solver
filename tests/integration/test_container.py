from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "Dockerfile"
ASSET_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "asset-build.yml"


class TestRunsAsNonRoot:
    def test_declares_a_user(self) -> None:
        lines = DOCKERFILE.read_text().splitlines()
        assert any(line.startswith("USER ") for line in lines)

    def test_the_user_is_not_root(self) -> None:
        lines = DOCKERFILE.read_text().splitlines()
        users = [
            line.split(maxsplit=1)[1].strip()
            for line in lines
            if line.startswith("USER ")
        ]
        assert users
        assert all(user not in {"root", "0"} for user in users)

    def test_the_user_is_created_before_it_is_switched_to(self) -> None:
        text = DOCKERFILE.read_text()
        assert text.index("useradd") < text.index("\nUSER ")


class TestLockfileInstalls:
    def test_dockerfile_uses_npm_ci(self) -> None:
        assert "npm ci" in DOCKERFILE.read_text()

    def test_dockerfile_does_not_use_npm_install(self) -> None:
        assert "npm install" not in DOCKERFILE.read_text()

    def test_asset_workflow_uses_npm_ci(self) -> None:
        assert "npm ci" in ASSET_WORKFLOW.read_text()

    def test_asset_workflow_does_not_use_npm_install(self) -> None:
        assert "npm install" not in ASSET_WORKFLOW.read_text()


def _dockerfile_cmd() -> str:
    for line in DOCKERFILE.read_text().splitlines():
        if line.startswith("CMD"):
            return line
    raise AssertionError("Dockerfile has no CMD line")


class TestSignalForwarding:
    def test_gunicorn_replaces_the_shell(self) -> None:
        assert "exec gunicorn" in _dockerfile_cmd()


class TestWorkerCount:
    PROCFILE = REPO_ROOT / "Procfile"

    def test_procfile_honours_web_concurrency(self) -> None:
        assert "WEB_CONCURRENCY" in self.PROCFILE.read_text()

    def test_dockerfile_honours_web_concurrency(self) -> None:
        assert "WEB_CONCURRENCY" in _dockerfile_cmd()

    def test_default_is_unchanged_at_two(self) -> None:
        for path in (self.PROCFILE, DOCKERFILE):
            assert "${WEB_CONCURRENCY:-2}" in path.read_text()
