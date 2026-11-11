import base64
import gzip
import hashlib
import json
import re
import struct
from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from flask.testing import FlaskClient
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.test import Client, TestResponse

import app as app_module
from app import app as flask_app
from relic_solver.config import (
    DEFAULT_RELIC_CAP,
    MAX_RELIC_CAP,
    MIN_RELIC_CAP,
)
from tests.integration.conftest import FakeRedis


def _parse_ndjson_results(resp: TestResponse) -> list[dict[str, Any]]:
    lines = resp.data.decode().strip().split("\n")
    messages = [json.loads(line) for line in lines if line.strip()]
    return [m for m in messages if m.get("type") == "result"]


def _js_source(name: str) -> str:
    return (_IMAGE_DIR.parent / "js" / name).read_text(encoding="utf-8")


def _raise_os_error(*_args: object, **_kwargs: object) -> str:
    raise OSError("no such file")


def _external_resource_tags(html: str) -> list[tuple[str, str]]:
    tags: list[tuple[str, str]] = []
    for match in re.finditer(r"<(script|link)\b[^>]*>", html, re.IGNORECASE):
        tag = match.group(0)
        if match.group(1).lower() == "link" and 'rel="stylesheet"' not in tag:
            continue
        url = re.search(r'(?:src|href)="(https?://[^"]+)"', tag)
        if url:
            tags.append((tag, url.group(1)))
    return tags


_IMAGE_DIR = Path(app_module.__file__).parent / "src" / "webapp" / "static" / "images"


def _image_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data[16:24])
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        chunk = data[12:16]
        if chunk == b"VP8L":
            bits = int.from_bytes(data[21:25], "little")
            return ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
        if chunk == b"VP8X":
            return (
                int.from_bytes(data[24:27], "little") + 1,
                int.from_bytes(data[27:30], "little") + 1,
            )
        if chunk == b"VP8 ":
            return struct.unpack("<HH", data[26:30])
    msg = f"{path.name}: unrecognised image header"
    raise AssertionError(msg)


class TestIndexRoute:
    def test_index_returns_200(self, client: FlaskClient) -> None:
        resp = client.get("/")
        assert resp.status_code == 200

    def test_index_is_html(self, client: FlaskClient) -> None:
        resp = client.get("/")
        assert "text/html" in resp.content_type

    def test_index_has_cache_control(self, client: FlaskClient) -> None:
        resp = client.get("/")
        assert "max-age=300" in resp.headers.get("Cache-Control", "")

    def test_index_contains_title(self, client: FlaskClient) -> None:
        resp = client.get("/")
        assert b"Relic Solver" in resp.data

    def test_index_has_one_topical_h1(self, client: FlaskClient) -> None:
        html = client.get("/").get_data(as_text=True)
        assert html.count("<h1") == 1
        h1 = re.search(r"<h1\b.*?</h1>", html, re.S)
        assert h1, "no h1 in the rendered page"
        text = re.sub(r"<[^>]+>", " ", h1.group(0))
        assert "Relic Solver" in text
        assert "Idle Obelisk Miner" in text

    def test_index_footer_carries_the_trust_signals(
        self,
        client: FlaskClient,
    ) -> None:
        html = client.get("/").get_data(as_text=True)
        footer = re.search(r"<footer\b.*?</footer>", html, re.S)
        assert footer, "no footer in the rendered page"
        markup = footer.group(0)
        assert 'rel="author"' in markup
        assert "github.com/Rovetown/Relic-Solver" in markup
        assert "apps.apple.com" in markup
        assert "<svg" in markup, "the GitHub mark has to be inlined"
        assert "GitHub" in markup, "the link text has to name the host"
        assert 'aria-hidden="true"' in markup
        assert "·" not in markup, "middot separators read as filler"

    def test_structured_data_names_an_author(self, client: FlaskClient) -> None:
        html = client.get("/").get_data(as_text=True)
        block = re.search(
            r'<script type="application/ld\+json">(.*?)</script>',
            html,
            re.S,
        )
        assert block, "no JSON-LD block in the rendered page"
        data = json.loads(block.group(1))
        assert data["@type"] == "WebApplication"
        assert data["author"]["name"] == "Rovetown"
        assert data["publisher"]["name"] == "Rovetown"

    def test_gem_figure_ships_its_icon(self, client: FlaskClient) -> None:
        html = client.get("/").get_data(as_text=True)
        row = re.search(
            r'<span class="result-detail result-detail--gems"[\s\S]*?</span>\s*</span>',
            html,
        )
        assert row, "no gem row in the rendered page"
        markup = row.group(0)
        assert "images/Gem.webp" in markup
        assert 'id="resultGems"' in markup
        assert 'alt=""' in markup, "the count already says 'gems'; icon is decorative"

    def test_template_bounds_match_config(self, client: FlaskClient) -> None:
        html = client.get("/").get_data(as_text=True)
        assert f'value="{DEFAULT_RELIC_CAP}"' in html
        assert f'min="{MIN_RELIC_CAP}"' in html
        assert html.count(f'max="{MAX_RELIC_CAP}"') == 5

    def test_every_input_names_its_help_text(self, client: FlaskClient) -> None:
        html = client.get("/").get_data(as_text=True)
        fields = [
            "totalRelicChests",
            "totalDivineChests",
            "relicCap",
            "targetD1",
            "targetD2",
            "targetD3",
            "targetD4",
            "targetD5",
        ]
        for field in fields:
            assert f'aria-describedby="help-{field}"' in html, field
            assert f'id="help-{field}"' in html, field
            assert f'<label for="{field}"' in html, field

    def test_inputs_start_in_a_valid_state(self, client: FlaskClient) -> None:
        html = client.get("/").get_data(as_text=True)
        assert html.count('aria-invalid="false"') == 8
        assert 'aria-invalid="true"' not in html

    def test_validation_runs_before_the_request(
        self,
        client: FlaskClient,
    ) -> None:
        js = _js_source("solver.js")
        assert "function validateInputs()" in js
        assert "if (!validateInputs()) return;" in js
        assert '.focus()' in js
        assert 'setAttribute("aria-invalid"' in js

    def test_client_hardening_is_in_place(self, client: FlaskClient) -> None:
        js = _js_source("solver.js")
        assert "new AbortController()" in js
        assert "REQUEST_TIMEOUT_MS = 120000" in js
        assert "ETAG_CACHE_MAX = 50" in js
        assert "function renderResult(" in js
        core = _js_source("solver-core.js")
        assert "function resultFrameProblem(" in core
        assert "function fieldProblem(" in core
        assert "showResult(cached.data)" not in js
        assert "saveInputsSoon" in js
        assert 'addEventListener("input", saveInputs)' not in js, (
            "saveInputs must be debounced, not bound raw to input"
        )
        assert "activeReader.cancel()" in js

    def test_injected_script_errors_stay_off_screen(
        self,
        client: FlaskClient,
    ) -> None:
        js = _js_source("solver.js")
        assert "function isOurScript(" in js
        assert "if (!isOurScript(event.filename)) return;" in js

    def test_the_form_opts_out_of_native_validation(
        self,
        client: FlaskClient,
    ) -> None:
        html = client.get("/").get_data(as_text=True)
        assert '<form id="solverForm" novalidate>' in html

    def test_asset_urls_are_fingerprinted_by_content(
        self,
        client: FlaskClient,
    ) -> None:
        html = client.get("/").get_data(as_text=True)
        versions = set(re.findall(r"[?]v=([0-9a-f]{8})", html))
        assert len(versions) == 2, versions
        assert app_module.solver_version not in versions

    def test_the_stylesheet_is_inlined_under_its_own_hash(
        self,
        client: FlaskClient,
    ) -> None:
        response = client.get("/")
        html = response.get_data(as_text=True)
        csp = response.headers["Content-Security-Policy"]

        digest = re.search(r"style-src 'self' 'sha256-([A-Za-z0-9+/=]+)'", csp)
        assert digest, csp

        block = re.search(r"<style>(.*?)</style>", html, re.DOTALL)
        assert block, "no inlined <style> on the page"
        expected = base64.b64encode(
            hashlib.sha256(block.group(1).encode("utf-8")).digest(),
        ).decode("ascii")
        assert digest.group(1) == expected, "the digest does not cover what shipped"
        assert "css/style.min.css" not in html, "stylesheet is still linked"

    def test_inlined_css_urls_are_rewritten_to_absolute_paths(
        self,
        client: FlaskClient,
    ) -> None:
        html = client.get("/").get_data(as_text=True)
        assert "url(../" not in html, "a relative url() survived inlining"
        assert "/static/images/" in html

    def test_a_missing_stylesheet_falls_back_to_a_link(
        self,
        client: FlaskClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            app_module,
            "_read_static_text",
            _raise_os_error,
        )
        html = client.get("/").get_data(as_text=True)
        assert "<style>" not in html
        assert 'href="/static/css/style.min.css?v=' in html

    def test_the_support_button_is_out_of_the_footer(
        self,
        client: FlaskClient,
    ) -> None:
        html = client.get("/").get_data(as_text=True)
        assert 'class="kofi-float"' in html
        assert "page-footer__support" not in html
        assert "ko-fi.com/rovetown" in html
        assert "images/kofi5.webp" in html

    def test_the_help_panels_need_no_framework_to_open(
        self,
        client: FlaskClient,
    ) -> None:
        html = client.get("/").get_data(as_text=True)
        assert "data-bs-" not in html, "a Bootstrap data attribute survived"
        for panel in ("inputHelp", "outputHelp"):
            assert f'aria-controls="{panel}"' in html
            assert f'id="{panel}"' in html

    def test_the_fingerprint_follows_the_bytes(self) -> None:
        first = app_module.asset_version("js/solver.js")
        app_module.asset_version.cache_clear()
        assert app_module.asset_version("js/solver.js") == first

        expected = hashlib.sha256(
            (_IMAGE_DIR.parent / "js" / "solver.js").read_bytes(),
        ).hexdigest()[:8]
        assert first == expected

    def test_a_missing_asset_does_not_crash_the_page(self) -> None:
        assert app_module.asset_version("js/not-here.js") == app_module.solver_version

    def test_footer_links_the_community_pages(
        self,
        client: FlaskClient,
    ) -> None:
        html = client.get("/").get_data(as_text=True)
        footer = re.search(r"<footer\b[\s\S]*?</footer>", html)
        assert footer, "no footer in the rendered page"
        markup = footer.group(0)
        assert "https://discord.gg/WKVUbbSJqA" in markup
        assert "https://github.com/Rovetown/Relic-Solver" in markup

    def test_the_kofi_button_is_served_from_our_own_origin(
        self,
        client: FlaskClient,
    ) -> None:
        for path in ("/", "/privacy", "/does-not-exist"):
            assert "ko-fi.com/cdn" not in client.get(path).get_data(as_text=True)
            assert "storage.ko-fi.com" not in client.get(path).get_data(as_text=True)

        resp = client.get("/static/images/kofi5.webp")
        assert resp.status_code == 200
        assert resp.headers["Content-Type"] == "image/webp"

        csp = client.get("/").headers["Content-Security-Policy"]
        assert "img-src 'self';" in csp, csp

    def test_the_core_module_loads_before_the_page_script(
        self,
        client: FlaskClient,
    ) -> None:
        html = client.get("/").get_data(as_text=True)
        core_at = html.find("js/solver-core.min.js")
        page_at = html.find("js/solver.min.js")
        assert core_at != -1, "solver-core.js is not loaded"
        assert page_at != -1, "solver.js is not loaded"
        assert core_at < page_at, "solver-core.js must come first"
        assert client.get("/static/js/solver-core.min.js").status_code == 200

    def test_the_page_loads_nothing_from_another_origin(
        self,
        client: FlaskClient,
    ) -> None:
        html = client.get("/").get_data(as_text=True)
        assert not _external_resource_tags(html), "page gained a third party"

    def test_any_external_resource_would_carry_sri(
        self,
        client: FlaskClient,
    ) -> None:
        html = client.get("/").get_data(as_text=True)
        external = _external_resource_tags(html)
        for tag, url in external:
            assert "integrity=" in tag, f"{url} has no integrity attribute"
            assert "crossorigin=" in tag, f"{url} has no crossorigin attribute"
            assert "sha384-" in tag or "sha512-" in tag, (
                f"{url} uses a weaker digest than sha384"
            )

    def test_template_has_no_stale_cap_literals(
        self, client: FlaskClient,
    ) -> None:
        html = client.get("/").get_data(as_text=True)
        for attr in ("min", "max"):
            for value in re.findall(rf'\s{attr}="(\d+)"', html):
                assert int(value) in {0, MIN_RELIC_CAP, MAX_RELIC_CAP}, (
                    f'{attr}="{value}" is not a config value'
                )


class TestStaticRoutes:
    def test_favicon_returns_200(self, client: FlaskClient) -> None:
        resp = client.get("/favicon.ico")
        assert resp.status_code == 200

    def test_robots_returns_200_or_404(self, client: FlaskClient) -> None:
        resp = client.get("/robots.txt")
        assert resp.status_code in (200, 404)

    def test_static_assets_are_immutable(self, client: FlaskClient) -> None:
        resp = client.get("/static/css/style.min.css")
        assert resp.status_code == 200
        assert resp.cache_control.immutable
        assert resp.cache_control.max_age == 31536000

    def test_root_served_files_stay_revalidatable(
        self,
        client: FlaskClient,
    ) -> None:
        for path in ("/robots.txt", "/sitemap.xml", "/manifest.json"):
            resp = client.get(path)
            assert resp.status_code == 200, path
            assert not resp.cache_control.immutable, path
            assert resp.cache_control.max_age == 3600, path

    def test_sitemap_is_rendered_with_a_lastmod(
        self,
        client: FlaskClient,
    ) -> None:
        resp = client.get("/sitemap.xml")
        assert resp.status_code == 200
        assert resp.headers["Content-Type"].startswith("application/xml")
        body = resp.get_data(as_text=True)
        assert "<loc>https://iomreliccalc.me/</loc>" in body
        assert re.search(r"<lastmod>\d{4}-\d{2}-\d{2}</lastmod>", body), body

    def test_privacy_page_is_reachable_and_linked(
        self,
        client: FlaskClient,
    ) -> None:
        resp = client.get("/privacy")
        assert resp.status_code == 200
        assert "max-age=3600" in resp.headers.get("Cache-Control", "")
        assert 'href="/privacy"' in client.get("/").get_data(as_text=True)

    def test_privacy_page_claims_match_the_code(
        self,
        client: FlaskClient,
    ) -> None:
        for path in ("/", "/privacy"):
            assert "Set-Cookie" not in client.get(path).headers, path
        resp = client.post(
            "/solve",
            json={
                "total_relic_chests": 10,
                "divine_chests": 1,
                "relic_cap": 20,
                "targets": [1, 0, 0, 0, 0],
            },
        )
        resp.get_data()
        assert "Set-Cookie" not in resp.headers

    def test_privacy_page_offers_an_erasure_control(
        self,
        client: FlaskClient,
    ) -> None:
        html = client.get("/privacy").get_data(as_text=True)
        assert 'id="clearStorage"' in html
        assert "hidden>" in html, "the control must not render without its script"
        assert "js/privacy.min.js" in html
        assert 'aria-live="polite"' in html

    def test_privacy_script_is_served(self, client: FlaskClient) -> None:
        resp = client.get("/static/js/privacy.min.js")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert '"relicSolverInputs"' in body

    def test_saved_inputs_carry_a_retention_window(
        self,
        client: FlaskClient,
    ) -> None:
        body = _js_source("solver.js")
        assert "STORAGE_MAX_AGE_MS = 90 * 24 * 60 * 60 * 1000" in body
        assert "savedAt" in body
        assert "90" in client.get("/privacy").get_data(as_text=True)

    def test_sitemap_lists_the_privacy_page(self, client: FlaskClient) -> None:
        body = client.get("/sitemap.xml").get_data(as_text=True)
        assert "<loc>https://iomreliccalc.me/privacy</loc>" in body

    def test_webp_assets_are_served_as_webp(self, client: FlaskClient) -> None:
        resp = client.get("/static/images/Relic_Chest.webp")
        assert resp.status_code == 200
        assert resp.headers["Content-Type"] == "image/webp"

    def test_every_image_extension_matches_its_bytes(
        self,
        client: FlaskClient,
    ) -> None:
        magic = {b"\x89PNG": ".png", b"RIFF": ".webp"}
        for path in sorted(_IMAGE_DIR.iterdir()):
            if not path.is_file() or path.suffix == ".ico":
                continue
            head = path.read_bytes()[:4]
            expected = magic.get(head)
            assert expected, f"{path.name}: unrecognised magic {head!r}"
            assert path.suffix == expected, (
                f"{path.name} holds {expected} data"
            )

    def test_sprites_render_at_their_native_size(
        self,
        client: FlaskClient,
    ) -> None:
        html = client.get("/").get_data(as_text=True)
        tags = re.findall(r"<img[^>]*>", html)
        assert tags, "no images in the rendered page"
        for tag in tags:
            src = re.search(r'src="/static/images/([^"]+)"', tag)
            if not src:
                continue
            if "kofi-button" in tag:
                continue
            width = re.search(r'\swidth="(\d+)"', tag)
            height = re.search(r'\sheight="(\d+)"', tag)
            assert width and height, f"{tag} declares no width/height"
            declared = (int(width.group(1)), int(height.group(1)))
            intrinsic = _image_size(_IMAGE_DIR / src.group(1))
            assert declared == intrinsic, (
                f"{src.group(1)}: drawn at {declared}, source is {intrinsic}"
            )


class TestSolveValidation:
    def test_missing_fields(self, client: FlaskClient) -> None:
        resp = client.post("/solve", json={})
        assert resp.status_code == 400
        data = resp.get_json()
        assert "Missing fields" in data["error"]

    def test_invalid_relic_cap_too_low(self, client: FlaskClient) -> None:
        resp = client.post(
            "/solve", json={
                "total_relic_chests": 1000,
                "divine_chests": 5,
                "relic_cap": MIN_RELIC_CAP - 1,
                "targets": [1, 0, 0, 0, 0],
            },
        )
        assert resp.status_code == 400
        assert "relic_cap" in resp.get_json()["error"]

    def test_invalid_relic_cap_too_high(self, client: FlaskClient) -> None:
        resp = client.post(
            "/solve", json={
                "total_relic_chests": 1000,
                "divine_chests": 5,
                "relic_cap": MAX_RELIC_CAP + 1,
                "targets": [1, 0, 0, 0, 0],
            },
        )
        assert resp.status_code == 400
        assert "relic_cap" in resp.get_json()["error"]

    def test_negative_chests(self, client: FlaskClient) -> None:
        resp = client.post(
            "/solve", json={
                "total_relic_chests": -1,
                "divine_chests": 5,
                "relic_cap": DEFAULT_RELIC_CAP,
                "targets": [1, 0, 0, 0, 0],
            },
        )
        assert resp.status_code == 400
        assert "non-negative" in resp.get_json()["error"]

    def test_wrong_target_count(self, client: FlaskClient) -> None:
        resp = client.post(
            "/solve", json={
                "total_relic_chests": 1000,
                "divine_chests": 5,
                "relic_cap": DEFAULT_RELIC_CAP,
                "targets": [1, 0, 0],
            },
        )
        assert resp.status_code == 400
        assert "5 values" in resp.get_json()["error"]

    def test_d2_target_exceeds_max_cap(self, client: FlaskClient) -> None:
        resp = client.post(
            "/solve", json={
                "total_relic_chests": 1000,
                "divine_chests": 5,
                "relic_cap": DEFAULT_RELIC_CAP,
                "targets": [0, MAX_RELIC_CAP + 1, 0, 0, 0],
            },
        )
        assert resp.status_code == 400
        assert "must not exceed" in resp.get_json()["error"]


class TestHealthEndpoint:
    def test_health_returns_200(self, client: FlaskClient) -> None:
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_health_contains_status_and_version(self, client: FlaskClient) -> None:
        resp = client.get("/api/health")
        data = resp.get_json()
        assert data["status"] == "ok"
        assert isinstance(data["solver_version"], str)
        assert "cache" in data


class TestResponseTiming:
    def test_index_has_response_time_header(self, client: FlaskClient) -> None:
        resp = client.get("/")
        assert "X-Response-Time" in resp.headers
        assert resp.headers["X-Response-Time"].endswith("ms")

    def test_health_has_response_time_header(self, client: FlaskClient) -> None:
        resp = client.get("/api/health")
        assert "X-Response-Time" in resp.headers


class TestSecurityHeaders:
    def test_csp_present(self, client: FlaskClient) -> None:
        resp = client.get("/")
        csp = resp.headers.get("Content-Security-Policy", "")
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp

    def test_csp_forbids_inline_styles(self, client: FlaskClient) -> None:
        csp = client.get("/").headers.get("Content-Security-Policy", "")
        assert "'unsafe-inline'" not in csp, csp

    def test_csp_names_no_host_outside_this_origin(
        self,
        client: FlaskClient,
    ) -> None:
        csp = client.get("/").headers.get("Content-Security-Policy", "")
        assert "connect-src 'self';" in csp, csp
        assert "cdn.jsdelivr.net" not in csp, csp

    def test_csp_sets_the_directives_that_do_not_inherit(
        self,
        client: FlaskClient,
    ) -> None:
        csp = client.get("/").headers.get("Content-Security-Policy", "")
        assert "base-uri 'self'" in csp, csp
        assert "form-action 'self'" in csp, csp

    def test_no_inline_style_attributes_remain(
        self,
        client: FlaskClient,
    ) -> None:
        for path in ("/", "/does-not-exist"):
            html = client.get(path).get_data(as_text=True)
            assert 'style="' not in html, path

    def test_csp_carries_a_style_hash(self, client: FlaskClient) -> None:
        csp = client.get("/").headers.get("Content-Security-Policy", "")
        assert "'sha256-" in csp
        assert "'nonce-" not in csp, "nonces do not survive an edge cache"

    def test_csp_is_identical_across_requests(self, client: FlaskClient) -> None:
        csp1 = client.get("/").headers["Content-Security-Policy"]
        csp2 = client.get("/").headers["Content-Security-Policy"]
        assert csp1 == csp2

    def test_a_page_with_nothing_inlined_has_a_bare_style_src(
        self,
        client: FlaskClient,
    ) -> None:
        csp = client.get("/privacy").headers["Content-Security-Policy"]
        assert "style-src 'self';" in csp, csp

    def test_x_frame_options(self, client: FlaskClient) -> None:
        resp = client.get("/")
        assert resp.headers["X-Frame-Options"] == "DENY"

    def test_x_content_type_options(self, client: FlaskClient) -> None:
        resp = client.get("/")
        assert resp.headers["X-Content-Type-Options"] == "nosniff"

    def test_xss_protection_disabled(self, client: FlaskClient) -> None:
        resp = client.get("/")
        assert resp.headers["X-XSS-Protection"] == "0"

    def test_referrer_policy(self, client: FlaskClient) -> None:
        resp = client.get("/")
        assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"

    def test_permissions_policy(self, client: FlaskClient) -> None:
        resp = client.get("/")
        assert "camera=()" in resp.headers["Permissions-Policy"]

    def test_hsts_only_behind_tls(self, client: FlaskClient) -> None:
        resp_plain = client.get("/")
        assert "Strict-Transport-Security" not in resp_plain.headers

        resp_tls = client.get("/", headers={"X-Forwarded-Proto": "https"})
        assert "max-age=31536000" in resp_tls.headers["Strict-Transport-Security"]


class TestHttpsRedirect:
    def test_no_redirect_when_disabled(self, client: FlaskClient) -> None:
        resp = client.get("/")
        assert resp.status_code == 200

    def test_redirects_plain_http(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            app_module,
            "settings",
            replace(app_module.settings, force_https=True),
        )
        resp = client.get("/")
        assert resp.status_code == 308
        assert resp.headers["Location"] == "https://localhost/"

    def test_redirect_csp_carries_no_inline_source(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            app_module,
            "settings",
            replace(app_module.settings, force_https=True),
        )
        csp = client.get("/").headers["Content-Security-Policy"]
        assert "'nonce-" not in csp, csp
        assert "'sha256-" not in csp, csp
        assert "script-src 'self';" in csp, csp
        assert "style-src 'self';" in csp, csp

    def test_redirect_preserves_query_string(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            app_module,
            "settings",
            replace(app_module.settings, force_https=True),
        )
        resp = client.get("/?a=1&b=2")
        assert resp.headers["Location"] == "https://localhost/?a=1&b=2"

    def test_post_keeps_method_via_308(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            app_module,
            "settings",
            replace(app_module.settings, force_https=True),
        )
        resp = client.post("/solve", json={})
        assert resp.status_code == 308

    def test_no_redirect_when_already_https(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            app_module,
            "settings",
            replace(app_module.settings, force_https=True),
        )
        resp = client.get("/", headers={"X-Forwarded-Proto": "https"})
        assert resp.status_code == 200


class TestProxyFix:
    @staticmethod
    def _probe(headers: dict[str, str]) -> dict[str, Any]:
        proxied = cast(ProxyFix, flask_app.wsgi_app)
        captured: dict[str, Any] = {}

        def inner(
            environ: dict[str, Any], start_response: Callable[..., Any],
        ) -> Iterable[bytes]:
            captured.update(environ)
            start_response("200 OK", [("Content-Type", "text/plain")])
            return [b""]

        original = proxied.app
        proxied.app = inner
        try:
            Client(proxied).get("/", headers=headers)
        finally:
            proxied.app = original
        return captured

    def test_client_ip_from_forwarded_for(self) -> None:
        env = self._probe({"X-Forwarded-For": "1.1.1.1, 203.0.113.7"})
        assert env["REMOTE_ADDR"] == "203.0.113.7"

    def test_scheme_from_forwarded_proto(self) -> None:
        env = self._probe({"X-Forwarded-Proto": "https"})
        assert env["wsgi.url_scheme"] == "https"

    def test_forwarded_host_is_ignored(self) -> None:
        env = self._probe({"X-Forwarded-Host": "evil.example"})
        assert env["HTTP_HOST"] == "localhost"


class TestCacheIntegration:
    def test_solve_works_without_redis(self, client: FlaskClient) -> None:
        resp = client.post(
            "/solve", json={
                "total_relic_chests": 0,
                "divine_chests": 5,
                "relic_cap": DEFAULT_RELIC_CAP,
                "targets": [1, 0, 0, 0, 0],
            },
        )
        results = _parse_ndjson_results(resp)
        assert len(results) == 1
        assert results[0]["probability"] == 1.0
        assert "cached" not in results[0]

    def test_health_shows_cache_disabled(self, client: FlaskClient) -> None:
        resp = client.get("/api/health")
        data = resp.get_json()
        assert data["cache"]["backend"] == "none"
        assert data["cache"]["entries"] is None


class TestSolveStreaming:
    def test_valid_solve_returns_ndjson(self, client: FlaskClient) -> None:
        resp = client.post(
            "/solve", json={
                "total_relic_chests": 0,
                "divine_chests": 5,
                "relic_cap": DEFAULT_RELIC_CAP,
                "targets": [1, 0, 0, 0, 0],
            },
        )
        assert resp.status_code == 200
        assert "ndjson" in resp.content_type

    def test_valid_solve_contains_result(self, client: FlaskClient) -> None:
        resp = client.post(
            "/solve", json={
                "total_relic_chests": 0,
                "divine_chests": 5,
                "relic_cap": DEFAULT_RELIC_CAP,
                "targets": [1, 0, 0, 0, 0],
            },
        )
        results = _parse_ndjson_results(resp)
        assert len(results) == 1
        assert results[0]["probability"] == 1.0

    def test_zero_target_returns_probability_one(self, client: FlaskClient) -> None:
        resp = client.post(
            "/solve", json={
                "total_relic_chests": 0,
                "divine_chests": 0,
                "relic_cap": DEFAULT_RELIC_CAP,
                "targets": [0, 0, 0, 0, 0],
            },
        )
        results = _parse_ndjson_results(resp)
        assert results[0]["probability"] == 1.0

    def test_result_contains_solve_time(self, client: FlaskClient) -> None:
        resp = client.post(
            "/solve", json={
                "total_relic_chests": 0,
                "divine_chests": 5,
                "relic_cap": DEFAULT_RELIC_CAP,
                "targets": [1, 0, 0, 0, 0],
            },
        )
        results = _parse_ndjson_results(resp)
        assert "solve_time_ms" in results[0]
        assert isinstance(results[0]["solve_time_ms"], float)

    def test_impossible_returns_zero_probability(self, client: FlaskClient) -> None:
        resp = client.post(
            "/solve", json={
                "total_relic_chests": 0,
                "divine_chests": 0,
                "relic_cap": DEFAULT_RELIC_CAP,
                "targets": [1, 0, 0, 0, 0],
            },
        )
        results = _parse_ndjson_results(resp)
        assert results[0]["probability"] == 0.0


_SOLVE_PAYLOAD: dict[str, object] = {
    "total_relic_chests": 0,
    "divine_chests": 5,
    "relic_cap": DEFAULT_RELIC_CAP,
    "targets": [1, 0, 0, 0, 0],
}


def _populate_cache(client: FlaskClient) -> None:
    resp = client.post("/solve", json=_SOLVE_PAYLOAD)
    _ = resp.data


class TestETagCacheHit:
    def test_cache_hit_includes_etag_header(
        self,
        client: FlaskClient,
        redis_client: FakeRedis,
    ) -> None:
        _populate_cache(client)

        resp = client.post("/solve", json=_SOLVE_PAYLOAD)
        assert resp.status_code == 200
        assert "ETag" in resp.headers
        assert resp.headers["ETag"].startswith('"')
        assert resp.headers["ETag"].endswith('"')

    def test_matching_etag_returns_304(
        self,
        client: FlaskClient,
        redis_client: FakeRedis,
    ) -> None:
        _populate_cache(client)

        resp = client.post("/solve", json=_SOLVE_PAYLOAD)
        etag = resp.headers["ETag"]

        resp = client.post(
            "/solve",
            json=_SOLVE_PAYLOAD,
            headers={"If-None-Match": etag},
        )
        assert resp.status_code == 304
        assert resp.headers["ETag"] == etag
        assert resp.data == b""

    def test_wrong_etag_returns_full_response(
        self,
        client: FlaskClient,
        redis_client: FakeRedis,
    ) -> None:
        _populate_cache(client)

        resp = client.post(
            "/solve",
            json=_SOLVE_PAYLOAD,
            headers={"If-None-Match": '"wrong"'},
        )
        assert resp.status_code == 200
        results = _parse_ndjson_results(resp)
        assert len(results) == 1
        assert results[0]["cached"] is True

    def test_cache_hit_result_marked_cached(
        self,
        client: FlaskClient,
        redis_client: FakeRedis,
    ) -> None:
        _populate_cache(client)
        resp = client.post("/solve", json=_SOLVE_PAYLOAD)
        results = _parse_ndjson_results(resp)
        assert results[0]["cached"] is True


class TestCacheMonitoring:
    def test_health_reports_redis_backend(
        self,
        client: FlaskClient,
        redis_client: FakeRedis,
    ) -> None:
        resp = client.get("/api/health")
        data = resp.get_json()
        assert data["cache"]["backend"] == "redis"

    def test_health_tracks_persistent_counters(
        self,
        client: FlaskClient,
        redis_client: FakeRedis,
    ) -> None:
        _populate_cache(client)
        client.post("/solve", json=_SOLVE_PAYLOAD)

        resp = client.get("/api/health")
        data = resp.get_json()
        cache = data["cache"]

        assert cache["total_hits"] >= 1
        assert cache["total_misses"] >= 1
        assert cache["instance_hits"] >= 1
        assert cache["instance_misses"] >= 1

    def test_health_reports_entry_count(
        self,
        client: FlaskClient,
        redis_client: FakeRedis,
    ) -> None:
        _populate_cache(client)

        resp = client.get("/api/health")
        data = resp.get_json()
        assert data["cache"]["entries"] >= 1

    def test_health_hit_rate_calculation(
        self,
        client: FlaskClient,
        redis_client: FakeRedis,
    ) -> None:
        _populate_cache(client)
        client.post("/solve", json=_SOLVE_PAYLOAD)

        resp = client.get("/api/health")
        data = resp.get_json()
        assert 0.0 <= data["cache"]["hit_rate"] <= 1.0


class TestCompression:
    _STATIC_JS = "/static/js/solver.min.js"

    def test_static_prefers_brotli(self, client: FlaskClient) -> None:
        resp = client.get(
            self._STATIC_JS,
            headers={"Accept-Encoding": "gzip, deflate, br, zstd"},
        )

        assert resp.status_code == 200
        assert resp.headers["Content-Encoding"] == "br"

    def test_static_compressed_for_gzip_only_client(
        self,
        client: FlaskClient,
    ) -> None:
        resp = client.get(self._STATIC_JS, headers={"Accept-Encoding": "gzip"})
        raw = client.get(self._STATIC_JS, headers={"Accept-Encoding": "identity"})

        assert resp.headers["Content-Encoding"] == "gzip"
        assert gzip.decompress(resp.data) == raw.data
        assert len(resp.data) < len(raw.data)

    def test_dynamic_response_compressed(self, client: FlaskClient) -> None:
        resp = client.get("/", headers={"Accept-Encoding": "gzip"})

        assert resp.headers["Content-Encoding"] == "gzip"
        assert b"<html" in gzip.decompress(resp.data).lower()

    def test_vary_header_set(self, client: FlaskClient) -> None:
        resp = client.get(self._STATIC_JS, headers={"Accept-Encoding": "gzip"})

        assert "accept-encoding" in resp.headers["Vary"].lower()

    def test_already_compressed_asset_untouched(
        self,
        client: FlaskClient,
    ) -> None:
        resp = client.get(
            "/static/fonts/press-start-2p-latin.woff2",
            headers={"Accept-Encoding": "gzip, deflate, br, zstd"},
        )

        assert resp.status_code == 200
        assert "Content-Encoding" not in resp.headers

    def test_identity_client_gets_plain_body(self, client: FlaskClient) -> None:
        resp = client.get(self._STATIC_JS, headers={"Accept-Encoding": "identity"})

        assert "Content-Encoding" not in resp.headers
        assert resp.data.startswith(b"/*") or b"function" in resp.data


class TestWhatsNewMarkup:
    def test_the_dialog_is_present(self, client: FlaskClient) -> None:
        html = client.get("/").get_data(as_text=True)
        assert '<dialog class="whatsnew" id="whatsNew"' in html

    def test_it_is_labelled_for_assistive_technology(
        self,
        client: FlaskClient,
    ) -> None:
        html = client.get("/").get_data(as_text=True)
        assert 'aria-labelledby="whatsNewTitle"' in html
        assert 'id="whatsNewTitle"' in html

    def test_it_carries_a_dismiss_button(self, client: FlaskClient) -> None:
        html = client.get("/").get_data(as_text=True)
        assert "data-whatsnew-dismiss" in html

    def test_it_uses_a_real_list(self, client: FlaskClient) -> None:
        html = client.get("/").get_data(as_text=True)
        assert '<ul class="whatsnew__list">' in html

    def test_only_the_solver_page_carries_it(self, client: FlaskClient) -> None:
        for path in ("/privacy", "/does-not-exist"):
            assert 'id="whatsNew"' not in client.get(path).get_data(as_text=True), path

    def test_the_script_and_the_markup_agree_on_the_version(self) -> None:
        source = (
            Path(app_module.__file__).parent
            / "src"
            / "webapp"
            / "static"
            / "js"
            / "solver.js"
        ).read_text(encoding="utf-8")
        versions = re.findall(r'VERSION = "([^"]+)"', source)
        assert len(versions) == 1, versions


class TestNoCommentsReachTheBrowser:
    def test_no_html_comments_in_any_page(self, client: FlaskClient) -> None:
        for path in ("/", "/privacy", "/does-not-exist"):
            html = client.get(path).get_data(as_text=True)
            assert "<!--" not in html, f"{path} ships an HTML comment"

    def test_the_templates_carry_no_comments_at_all(self) -> None:
        templates = Path(app_module.__file__).parent / "src" / "webapp" / "templates"
        for name in ("index.html", "privacy.html", "404.html"):
            source = (templates / name).read_text(encoding="utf-8")
            assert "{#" not in source, f"{name} grew a Jinja comment back"
            assert "<!--" not in source, f"{name} grew an HTML comment back"


class TestSecurityTxt:
    WELL_KNOWN = "/.well-known/security.txt"
    PGP_KEY = "/.well-known/pgp-key.txt"
    FINGERPRINT = "eed2386b40494cdcf8b61b4cddd85342d44d6be0"  # pragma: allowlist secret

    @staticmethod
    def _fields(body: str) -> dict[str, list[str]]:
        fields: dict[str, list[str]] = {}
        for line in body.splitlines():
            if not line or line.startswith(("#", "-----", "Hash:")):
                continue
            name, _, value = line.partition(":")
            if value:
                fields.setdefault(name.strip().lower(), []).append(value.strip())
        return fields

    def test_security_txt_is_served_as_plain_utf8(
        self,
        client: FlaskClient,
    ) -> None:
        resp = client.get(self.WELL_KNOWN)
        assert resp.status_code == 200
        assert resp.headers["Content-Type"] == "text/plain; charset=utf-8"

    def test_security_txt_is_clearsigned(self, client: FlaskClient) -> None:
        body = client.get(self.WELL_KNOWN).get_data(as_text=True)
        assert body.startswith("-----BEGIN PGP SIGNED MESSAGE-----"), body[:80]
        assert "-----BEGIN PGP SIGNATURE-----" in body
        assert body.rstrip().endswith("-----END PGP SIGNATURE-----")

    def test_the_required_fields_are_present_exactly_once(
        self,
        client: FlaskClient,
    ) -> None:
        fields = self._fields(client.get(self.WELL_KNOWN).get_data(as_text=True))
        assert fields["contact"], fields
        for name in ("expires", "preferred-languages", "canonical"):
            assert len(fields[name]) == 1, f"{name}: {fields.get(name)}"

    def test_expires_is_in_the_future_and_under_a_year_out(
        self,
        client: FlaskClient,
    ) -> None:
        fields = self._fields(client.get(self.WELL_KNOWN).get_data(as_text=True))
        expires = datetime.fromisoformat(fields["expires"][0])
        now = datetime.now(UTC)
        assert expires > now + timedelta(days=30), (
            f"security.txt expires {expires.isoformat()}; re-sign it with "
            f"a later Expires via `just security-txt`"
        )
        assert expires < now + timedelta(days=365), expires.isoformat()

    def test_canonical_names_the_url_the_file_is_served_at(
        self,
        client: FlaskClient,
    ) -> None:
        fields = self._fields(client.get(self.WELL_KNOWN).get_data(as_text=True))
        assert fields["canonical"] == [
            f"https://iomreliccalc.me{self.WELL_KNOWN}",
        ]

    def test_encryption_points_at_the_key_that_is_served(
        self,
        client: FlaskClient,
    ) -> None:
        fields = self._fields(client.get(self.WELL_KNOWN).get_data(as_text=True))
        assert f"https://iomreliccalc.me{self.PGP_KEY}" in fields["encryption"]
        assert f"openpgp4fpr:{self.FINGERPRINT}" in fields["encryption"]

    def test_the_pgp_key_is_a_public_key_block(
        self,
        client: FlaskClient,
    ) -> None:
        resp = client.get(self.PGP_KEY)
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert body.startswith("-----BEGIN PGP PUBLIC KEY BLOCK-----"), body[:80]
        assert "PRIVATE KEY" not in body

    def test_the_key_carries_the_contact_address_as_a_uid(
        self,
        client: FlaskClient,
    ) -> None:
        source = Path(app_module.__file__).parent / "scripts" / "security.txt.in"
        text = source.read_text(encoding="utf-8")
        fields = self._fields(client.get(self.WELL_KNOWN).get_data(as_text=True))
        for contact in fields["contact"]:
            if contact.startswith("mailto:"):
                assert contact.removeprefix("mailto:") in text

    def test_both_well_known_files_stay_revalidatable(
        self,
        client: FlaskClient,
    ) -> None:
        for path in (self.WELL_KNOWN, self.PGP_KEY):
            resp = client.get(path)
            assert not resp.cache_control.immutable, path
            assert resp.cache_control.max_age == 3600, path

    def test_the_legacy_root_path_redirects(self, client: FlaskClient) -> None:
        resp = client.get("/security.txt")
        assert resp.status_code == 301
        assert resp.headers["Location"] == self.WELL_KNOWN

    def test_other_well_known_probes_still_answer_204(
        self,
        client: FlaskClient,
    ) -> None:
        resp = client.get("/.well-known/appspecific/com.chrome.devtools.json")
        assert resp.status_code == 204

    def test_robots_does_not_hide_the_contact_file(
        self,
        client: FlaskClient,
    ) -> None:
        body = client.get("/robots.txt").get_data(as_text=True)
        assert f"Allow: {self.WELL_KNOWN}" in body
        assert f"Allow: {self.PGP_KEY}" in body
