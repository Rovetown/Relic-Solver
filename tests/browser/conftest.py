import re
import socket
import subprocess  # nosec B404 - fixed argv below, never a shell
import sys
import time
from collections.abc import Generator
from pathlib import Path

import pytest
from playwright.sync_api import Page

_REPO_ROOT = Path(__file__).resolve().parents[2]
_STARTUP_TIMEOUT_S = 30.0
_SOLVER_JS = _REPO_ROOT / "src" / "webapp" / "static" / "js" / "solver.js"


def _whats_new_version() -> str:
    match = re.search(r'VERSION = "([^"]+)"', _SOLVER_JS.read_text(encoding="utf-8"))
    if match is None:
        msg = f"no what's-new VERSION found in {_SOLVER_JS}"
        raise RuntimeError(msg)
    return match.group(1)


@pytest.fixture(autouse=True)
def _whats_new_already_seen(request: pytest.FixtureRequest, page: Page) -> None:
    if request.node.get_closest_marker("shows_whats_new"):
        return
    page.add_init_script(
        "try { localStorage.setItem('relicSolver.whatsNew', "
        f'"{_whats_new_version()}"); }} catch {{}}',
    )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_until_serving(
    port: int,
    process: subprocess.Popen[bytes],
    log: Path,
) -> None:
    deadline = time.monotonic() + _STARTUP_TIMEOUT_S
    while time.monotonic() < deadline:
        if process.poll() is not None:
            out = log.read_text(encoding="utf-8", errors="replace")
            msg = f"server exited with {process.returncode} before serving:\n{out}"
            raise RuntimeError(msg)
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    msg = f"server did not answer on port {port} within {_STARTUP_TIMEOUT_S}s"
    raise RuntimeError(msg)


@pytest.fixture(scope="session")
def live_server(tmp_path_factory: pytest.TempPathFactory) -> Generator[str]:
    port = _free_port()
    log = tmp_path_factory.mktemp("live-server") / "server.log"
    with log.open("wb") as sink:
        process = subprocess.Popen(  # noqa: S603  # nosec B603 - fixed argv, no shell
            [sys.executable, "-m", "tests.browser._live_app", str(port)],
            cwd=_REPO_ROOT,
            stdout=sink,
            stderr=subprocess.STDOUT,
        )
        try:
            _wait_until_serving(port, process, log)
            yield f"http://127.0.0.1:{port}"
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
