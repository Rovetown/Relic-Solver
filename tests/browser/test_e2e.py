import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.browser

_RESULT_TIMEOUT_MS = 30_000


def _fill_solver(page: Page, chests: str, divines: str, cap: str) -> None:
    page.fill("#totalRelicChests", chests)
    page.fill("#totalDivineChests", divines)
    page.fill("#relicCap", cap)


class TestSolveFlow:
    def test_a_solve_renders_a_probability(self, page: Page, live_server: str) -> None:
        page.goto(live_server + "/")
        _fill_solver(page, "100", "5", "20")
        page.fill("#targetD1", "1")
        page.click("#runSolver")

        results = page.locator("#results")
        expect(results).to_be_visible(timeout=_RESULT_TIMEOUT_MS)
        expect(page.locator("#resultProbability")).to_have_text(
            re.compile(r"^\d+(\.\d+)?(e-\d+)?%$"),
            timeout=_RESULT_TIMEOUT_MS,
        )
        expect(page.locator("#errorBox")).not_to_be_visible()

    def test_the_gem_figure_and_its_sprite_appear_together(
        self,
        page: Page,
        live_server: str,
    ) -> None:
        page.goto(live_server + "/")
        _fill_solver(page, "100", "5", "20")
        page.fill("#targetD1", "1")
        page.click("#runSolver")

        row = page.locator("#resultGemsRow")
        expect(row).to_be_visible(timeout=_RESULT_TIMEOUT_MS)
        expect(page.locator("#resultGems")).to_have_text(re.compile(r"gems$"))
        expect(row.locator("img.result-icon")).to_be_visible()

    def test_an_impossible_result_hides_the_gem_figure(
        self,
        page: Page,
        live_server: str,
    ) -> None:
        page.goto(live_server + "/")
        _fill_solver(page, "1", "0", "5")
        page.fill("#targetD2", "5")
        page.click("#runSolver")

        expect(page.locator("#results")).to_be_visible(timeout=_RESULT_TIMEOUT_MS)
        expect(page.locator("#resultProbability")).to_contain_text("Impossible")
        expect(page.locator("#resultGemsRow")).not_to_be_visible()


class TestValidation:
    def test_an_out_of_range_cap_is_caught_without_a_request(
        self,
        page: Page,
        live_server: str,
    ) -> None:
        requests: list[str] = []
        page.on("request", lambda r: requests.append(r.url))

        page.goto(live_server + "/")
        page.fill("#relicCap", "1")
        page.click("#runSolver")

        expect(page.locator("#errorBox")).to_be_visible()
        expect(page.locator("#errorMessage")).to_contain_text("Divine Relic Cap")
        expect(page.locator("#relicCap")).to_have_attribute("aria-invalid", "true")
        expect(page.locator("#relicCap")).to_be_focused()
        assert not [u for u in requests if u.endswith("/solve")], (
            "a request the browser already knew was invalid was still sent"
        )

    def test_correcting_a_field_clears_its_invalid_state(
        self,
        page: Page,
        live_server: str,
    ) -> None:
        page.goto(live_server + "/")
        page.fill("#relicCap", "1")
        page.click("#runSolver")
        expect(page.locator("#relicCap")).to_have_attribute("aria-invalid", "true")

        page.fill("#relicCap", "20")
        expect(page.locator("#relicCap")).to_have_attribute("aria-invalid", "false")

    def test_an_empty_field_is_reported_not_coerced(
        self,
        page: Page,
        live_server: str,
    ) -> None:
        page.goto(live_server + "/")
        page.fill("#totalRelicChests", "")
        page.click("#runSolver")

        expect(page.locator("#errorMessage")).to_contain_text("needs a number")


class TestInputPersistence:
    def test_inputs_reach_the_url_after_typing_stops(
        self,
        page: Page,
        live_server: str,
    ) -> None:
        page.goto(live_server + "/")
        page.fill("#totalRelicChests", "1234")
        expect(page).to_have_url(re.compile(r"chests=1234"), timeout=5_000)

    def test_a_shared_url_fills_the_form(self, page: Page, live_server: str) -> None:
        page.goto(live_server + "/?chests=777&divine=9&cap=15")
        expect(page.locator("#totalRelicChests")).to_have_value("777")
        expect(page.locator("#totalDivineChests")).to_have_value("9")
        expect(page.locator("#relicCap")).to_have_value("15")

    def test_saved_inputs_survive_a_reload(
        self,
        page: Page,
        live_server: str,
    ) -> None:
        page.goto(live_server + "/")
        page.fill("#totalRelicChests", "4321")
        expect(page).to_have_url(re.compile(r"chests=4321"), timeout=5_000)

        page.goto(live_server + "/")
        expect(page.locator("#totalRelicChests")).to_have_value("4321")

    def test_the_stored_entry_carries_a_timestamp(
        self,
        page: Page,
        live_server: str,
    ) -> None:
        page.goto(live_server + "/")
        page.fill("#relicCap", "19")
        expect(page).to_have_url(re.compile(r"cap=19"), timeout=5_000)

        entry = page.evaluate(
            "JSON.parse(localStorage.getItem('relicSolverInputs'))",
        )
        assert isinstance(entry, dict), entry
        assert isinstance(entry.get("savedAt"), int | float)
        assert entry["values"]["relicCap"] == "19"


class TestPrivacyControl:
    def test_clearing_saved_inputs_works_and_says_so(
        self,
        page: Page,
        live_server: str,
    ) -> None:
        page.goto(live_server + "/")
        page.fill("#relicCap", "19")
        expect(page).to_have_url(re.compile(r"cap=19"), timeout=5_000)

        page.goto(live_server + "/privacy")
        button = page.locator("#clearStorage")
        expect(button).to_be_visible()
        expect(button).to_be_enabled()
        expect(page.locator("#clearStorageStatus")).to_contain_text("are saved")

        button.click()
        expect(page.locator("#clearStorageStatus")).to_contain_text("cleared")
        expect(button).to_be_disabled()
        assert page.evaluate(
            "localStorage.getItem('relicSolverInputs')",
        ) is None

    def test_the_control_reports_an_empty_store(
        self,
        page: Page,
        live_server: str,
    ) -> None:
        page.goto(live_server + "/privacy")
        expect(page.locator("#clearStorageStatus")).to_contain_text("Nothing is saved")
        expect(page.locator("#clearStorage")).to_be_disabled()


class TestRendering:
    def test_sprites_are_laid_out_at_their_native_size(
        self,
        page: Page,
        live_server: str,
    ) -> None:
        page.goto(live_server + "/")
        mismatches = page.evaluate(
            "() => Array.from(document.querySelectorAll('img'))"
            ".filter(img => img.offsetParent !== null)"
            ".filter(img => !img.classList.contains('kofi-button'))"
            ".map(img => ({"
            "  src: img.currentSrc.split('/').pop(),"
            "  natural: [img.naturalWidth, img.naturalHeight],"
            "  box: [Math.round(img.getBoundingClientRect().width),"
            "        Math.round(img.getBoundingClientRect().height)]"
            "}))"
            ".filter(i => i.natural[0] !== i.box[0] || i.natural[1] !== i.box[1])",
        )
        assert mismatches == [], mismatches

    def test_the_gem_sprite_is_also_laid_out_1_to_1(
        self,
        page: Page,
        live_server: str,
    ) -> None:
        page.goto(live_server + "/")
        page.fill("#totalRelicChests", "100")
        page.fill("#totalDivineChests", "5")
        page.fill("#relicCap", "20")
        page.fill("#targetD1", "1")
        page.click("#runSolver")
        page.wait_for_selector("#resultGemsRow.visible", timeout=_RESULT_TIMEOUT_MS)

        box = page.evaluate(
            """() => {
                const img = document.querySelector('#resultGemsRow img.result-icon');
                const r = img.getBoundingClientRect();
                return {
                    natural: [img.naturalWidth, img.naturalHeight],
                    box: [Math.round(r.width), Math.round(r.height)],
                };
            }""",
        )
        assert box["natural"] == box["box"], box

    def test_the_page_does_not_scroll_sideways_on_a_phone(
        self,
        page: Page,
        live_server: str,
    ) -> None:
        page.set_viewport_size({"width": 360, "height": 740})
        page.goto(live_server + "/")
        overflow = page.evaluate(
            "(() => {const d = document.documentElement;"
            " return d.scrollWidth - d.clientWidth;})()",
        )
        assert overflow <= 0, f"{overflow}px of horizontal overflow"

    def test_no_console_errors_on_any_page(
        self,
        page: Page,
        live_server: str,
    ) -> None:
        problems: list[str] = []
        page.on(
            "console",
            lambda m: problems.append(f"{m.type}: {m.text}")
            if m.type == "error"
            else None,
        )
        page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))

        for path in ("/", "/privacy"):
            page.goto(live_server + path)
            page.wait_for_load_state("networkidle")
        assert problems == [], problems

    def test_the_404_page_has_no_scripting_errors(
        self,
        page: Page,
        live_server: str,
    ) -> None:
        problems: list[str] = []
        page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
        page.goto(live_server + "/does-not-exist")
        page.wait_for_load_state("networkidle")
        assert problems == [], problems


@pytest.mark.shows_whats_new
class TestWhatsNewDialog:
    STORAGE_KEY = "relicSolver.whatsNew"

    def _is_open(self, page: Page) -> bool:
        return bool(page.evaluate("() => document.getElementById('whatsNew').open"))

    def _stored(self, page: Page) -> str | None:
        value = page.evaluate(
            "(key) => localStorage.getItem(key)",
            self.STORAGE_KEY,
        )
        return None if value is None else str(value)

    def test_it_opens_on_a_first_visit(self, page: Page, live_server: str) -> None:
        page.goto(live_server + "/")
        assert self._is_open(page)

    def test_focus_lands_on_the_dismiss_button(
        self,
        page: Page,
        live_server: str,
    ) -> None:
        page.goto(live_server + "/")
        expect(page.locator("[data-whatsnew-dismiss]")).to_be_focused()

    def test_escape_closes_without_remembering(
        self,
        page: Page,
        live_server: str,
    ) -> None:
        page.goto(live_server + "/")
        page.keyboard.press("Escape")
        assert not self._is_open(page)
        assert self._stored(page) is None

        page.reload()
        assert self._is_open(page), "escape should not have been remembered"

    def test_the_button_closes_and_remembers(
        self,
        page: Page,
        live_server: str,
    ) -> None:
        page.goto(live_server + "/")
        page.click("[data-whatsnew-dismiss]")
        assert not self._is_open(page)
        assert self._stored(page) is not None

        page.reload()
        assert not self._is_open(page)

    def test_the_solver_still_works_once_dismissed(
        self,
        page: Page,
        live_server: str,
    ) -> None:
        page.goto(live_server + "/")
        page.click("[data-whatsnew-dismiss]")
        _fill_solver(page, "100", "10", "5")
        expect(page.locator("#totalRelicChests")).to_have_value("100")

    def test_a_stale_version_shows_the_notes_again(
        self,
        page: Page,
        live_server: str,
    ) -> None:
        page.goto(live_server + "/")
        page.evaluate(
            "(key) => localStorage.setItem(key, '1970-01-01')",
            self.STORAGE_KEY,
        )
        page.reload()
        assert self._is_open(page)
