from typing import Any

import pytest
from axe_playwright_python.sync_playwright import Axe
from playwright.sync_api import Page

pytestmark = pytest.mark.browser

_PAGES = ("/", "/privacy", "/does-not-exist")


def _violations(page: Page) -> list[dict[str, Any]]:
    results = Axe().run(page)
    return list(results.response.get("violations", []))


def _describe(violations: list[dict[str, Any]]) -> str:
    lines = []
    for v in violations:
        targets = ", ".join(
            str(t) for node in v.get("nodes", []) for t in node.get("target", [])
        )
        lines.append(f"[{v.get('impact')}] {v.get('id')}: {v.get('help')} -> {targets}")
    return "\n".join(lines)


@pytest.mark.parametrize("path", _PAGES)
def test_no_accessibility_violations(page: Page, live_server: str, path: str) -> None:
    page.goto(live_server + path)
    page.wait_for_load_state("networkidle")
    violations = _violations(page)
    assert violations == [], f"{path}:\n{_describe(violations)}"


def test_no_violations_once_a_result_is_showing(
    page: Page,
    live_server: str,
) -> None:
    page.goto(live_server + "/")
    page.fill("#totalRelicChests", "100")
    page.fill("#totalDivineChests", "5")
    page.fill("#relicCap", "20")
    page.fill("#targetD1", "1")
    page.click("#runSolver")
    page.wait_for_selector("#results.visible", timeout=30_000)

    violations = _violations(page)
    assert violations == [], _describe(violations)


def test_no_violations_while_an_error_is_showing(
    page: Page,
    live_server: str,
) -> None:
    page.goto(live_server + "/")
    page.fill("#relicCap", "1")
    page.click("#runSolver")
    page.wait_for_selector("#errorBox.visible")

    violations = _violations(page)
    assert violations == [], _describe(violations)


def test_no_violations_with_the_help_panels_open(
    page: Page,
    live_server: str,
) -> None:
    page.goto(live_server + "/")
    for panel in ("#inputHelp", "#outputHelp"):
        page.click(f'button[aria-controls="{panel[1:]}"]')
    page.wait_for_selector("#inputHelp.show")
    page.wait_for_selector("#outputHelp.show")

    violations = _violations(page)
    assert violations == [], _describe(violations)


def test_each_input_has_an_accessible_description(
    page: Page,
    live_server: str,
) -> None:
    page.goto(live_server + "/")
    unresolved = page.evaluate(
        r"""() => Array.from(document.querySelectorAll(

            'input[aria-describedby], select[aria-describedby]',
        ))
            .flatMap(el => el.getAttribute('aria-describedby')
                .split(/\s+/)
                .filter(ref => ref.length > 0)
                .map(ref => ({
                    id: el.id,
                    ref: ref,
                    text: (document.getElementById(ref)?.textContent || '').trim(),
                })))
            .filter(i => i.text.length === 0)
        """
                                                ,
    )
    assert unresolved == [], unresolved


def test_the_whole_form_is_reachable_by_keyboard(
    page: Page,
    live_server: str,
) -> None:
    page.goto(live_server + "/")
    page.locator("#totalRelicChests").focus()

    seen: list[str] = []
    for _ in range(40):
        active = page.evaluate("document.activeElement?.id || ''")
        if active:
            seen.append(active)
        if active == "runSolver":
            break
        page.keyboard.press("Tab")

    expected = [
        "totalRelicChests",
        "totalDivineChests",
        "relicCap",
        "obeliskLevel",
        "targetD1",
        "targetD2",
        "targetD3",
        "targetD4",
        "targetD5",
        "runSolver",
    ]
    missing = [field for field in expected if field not in seen]
    assert missing == [], f"never focused: {missing} (saw {seen})"
