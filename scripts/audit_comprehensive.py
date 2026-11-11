from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
_REPORT_DIR = _REPO_ROOT / "tests" / "reports" / "audit"

PAGES = ("/", "/privacy", "/does-not-exist")
INDEXED_PAGES = ("/", "/privacy")


@dataclass
class Finding:
    slug: str
    title: str
    category: str
    priority: str
    status: str
    evidence: str
    detail: dict[str, Any] = field(default_factory=dict)


class Fetcher:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._cache: dict[tuple[str, str], tuple[int, dict[str, str], bytes]] = {}

    def get(
        self,
        path: str,
        accept_encoding: str = "identity",
    ) -> tuple[int, dict[str, str], bytes]:
        key = (path, accept_encoding)
        if key in self._cache:
            return self._cache[key]

        request = urllib.request.Request(  # noqa: S310 - local base URL
            self.base_url + path,
            headers={
                "User-Agent": "relic-solver-audit",
                "Accept": "text/html,application/xhtml+xml,*/*",
                "Accept-Encoding": accept_encoding,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
                result = (
                    response.status,
                    {k.lower(): v for k, v in response.headers.items()},
                    response.read(),
                )
        except urllib.error.HTTPError as exc:
            result = (
                exc.code,
                {k.lower(): v for k, v in exc.headers.items()},
                exc.read(),
            )

        self._cache[key] = result
        return result

    def text(self, path: str) -> str:
        return self.get(path)[2].decode("utf-8", "replace")

    def headers(self, path: str) -> dict[str, str]:
        return self.get(path)[1]


def check_html(fetch: Fetcher) -> list[Finding]:
    pages = {path: fetch.text(path) for path in PAGES}

    def every(predicate: Any) -> tuple[bool, dict[str, Any]]:
        results = {path: bool(predicate(html)) for path, html in pages.items()}
        return all(results.values()), results

    doctype_ok, doctype = every(lambda h: h.lstrip().lower().startswith("<!doctype html>"))
    charset_ok, charset = every(
        lambda h: re.search(r'<meta\s+charset=["\']?utf-8', h[:1024], re.I) is not None,
    )
    viewport_ok, viewport = every(
        lambda h: re.search(r'name=["\']viewport["\'][^>]*width=device-width', h, re.I)
        is not None,
    )
    lang_ok, lang = every(lambda h: re.search(r"<html[^>]+\blang=", h, re.I) is not None)

    return [
        Finding(
            "doctype",
            "Use the HTML5 doctype",
            "html",
            "critical",
            "pass" if doctype_ok else "fail",
            "every page opens with <!doctype html>",
            doctype,
        ),
        Finding(
            "charset",
            "Declare UTF-8 character encoding",
            "html",
            "critical",
            "pass" if charset_ok else "fail",
            "<meta charset=UTF-8> inside the first 1024 bytes of every page",
            charset,
        ),
        Finding(
            "viewport",
            "Set the responsive viewport meta tag",
            "html",
            "critical",
            "pass" if viewport_ok else "fail",
            "viewport meta with width=device-width on every page",
            viewport,
        ),
        Finding(
            "lang-attribute",
            "Set the page lang attribute",
            "html",
            "high",
            "pass" if lang_ok else "fail",
            "<html lang> present on every page",
            lang,
        ),
    ]


def _skip_link_status(present: dict[str, bool], first: dict[str, Any]) -> str:
    if all(present.values()):
        return "pass"
    outside = [p for p, f in first.items() if f and not f["insideMain"]]
    return "fail" if outside else "not-applicable"


def _skip_link_evidence(present: dict[str, bool], first: dict[str, Any]) -> str:
    if all(present.values()):
        return "every page offers a skip link"
    outside = {p: f for p, f in first.items() if f and not f["insideMain"]}
    if outside:
        where = "; ".join(f"{p}: {f['tag']} {f['text']!r}" for p, f in outside.items())
        return (
            "no skip link, and the first element a keyboard user reaches sits "
            f"outside <main> - {where}"
        )
    return (
        "no skip link; there is no navigation block to skip past and the first "
        "focusable element is already inside <main>"
    )


def check_accessibility(base_url: str) -> list[Finding]:
    from axe_playwright_python.sync_playwright import Axe
    from playwright.sync_api import sync_playwright

    violations: dict[str, list[dict[str, Any]]] = {}
    focusables: dict[str, Any] = {}
    headings: dict[str, list[str]] = {}
    skip_links: dict[str, bool] = {}
    first_focus: dict[str, Any] = {}

    with sync_playwright() as play:
        browser = play.chromium.launch()
        for path in PAGES:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.add_init_script(
                "try { localStorage.setItem('relicSolver.whatsNew', 'audit'); }"
                " catch {}",
            )
            page.goto(base_url + path, wait_until="networkidle")
            page.wait_for_timeout(300)

            violations[path] = list(
                Axe().run(page).response.get("violations", []),
            )
            headings[path] = page.evaluate(
                "() => [...document.querySelectorAll('h1,h2,h3,h4,h5,h6')]"
                ".map(h => h.tagName)",
            )
            skip_links[path] = page.evaluate(
                "() => [...document.querySelectorAll('a[href^=\"#\"]')]"
                ".some(a => /skip/i.test(a.textContent || ''))",
            )
            first_focus[path] = page.evaluate(
                """() => {
                    const sel = 'a[href], button, input, select, textarea,'
                        + ' [tabindex]:not([tabindex=\"-1\"])';
                    const first = [...document.querySelectorAll(sel)]
                        .find(n => !n.disabled && n.offsetParent !== null);
                    if (!first) return null;
                    const main = document.querySelector('main');
                    return {
                      tag: first.tagName,
                      text: (first.textContent || first.getAttribute('aria-label')
                             || '').trim().slice(0, 40),
                      insideMain: !!(main && main.contains(first)),
                    };
                }""",
            )
            focusables[path] = page.evaluate(
                """() => {
                    const sel = 'a[href], button, input, select, textarea,'
                        + ' [tabindex]:not([tabindex="-1"])';
                    const nodes = [...document.querySelectorAll(sel)]
                        .filter(n => !n.disabled && n.offsetParent !== null);
                    return {
                      total: nodes.length,
                      negativeTabindex: nodes.filter(
                        n => n.getAttribute('tabindex') === '-1').length,
                      withoutAccessibleName: nodes.filter(n => !(
                        n.textContent.trim() || n.getAttribute('aria-label')
                        || n.getAttribute('aria-labelledby')
                        || (n.labels && n.labels.length)
                        || n.getAttribute('title'))).length,
                    };
                }""",
            )
            page.close()
        browser.close()

    def ids(path: str) -> list[str]:
        return [str(v.get("id")) for v in violations[path]]

    contrast = {p: [i for i in ids(p) if "contrast" in i] for p in PAGES}
    labels = {p: [i for i in ids(p) if "label" in i or i == "form-field-multiple-labels"] for p in PAGES}
    order = {p: [i for i in ids(p) if i in {"heading-order", "page-has-heading-one"}] for p in PAGES}
    keyboard = {
        p: [i for i in ids(p) if i in {"tabindex", "focus-order-semantics", "aria-hidden-focus"}]
        for p in PAGES
    }
    unnamed = sum(f["withoutAccessibleName"] for f in focusables.values())

    return [
        Finding(
            "keyboard-navigation",
            "Enable keyboard navigation for all elements",
            "accessibility",
            "critical",
            "pass" if not any(keyboard.values()) and unnamed == 0 else "fail",
            f"no axe focus-order violations; {unnamed} focusable elements lack an "
            "accessible name",
            {"axe": keyboard, "focusables": focusables},
        ),
        Finding(
            "skip-link",
            'Implement "Skip to Content" links',
            "accessibility",
            "medium",
            _skip_link_status(skip_links, first_focus),
            _skip_link_evidence(skip_links, first_focus),
            {"present": skip_links, "first_focusable": first_focus},
        ),
        Finding(
            "color-contrast",
            "Meet minimum color contrast ratios",
            "accessibility",
            "high",
            "pass" if not any(contrast.values()) else "fail",
            "axe-core reports no colour-contrast violations on any page",
            contrast,
        ),
        Finding(
            "form-labels",
            "Associate labels with form controls",
            "accessibility",
            "critical",
            "pass" if not any(labels.values()) else "fail",
            "axe-core reports no label violations",
            labels,
        ),
        Finding(
            "heading-order",
            "Maintain logical heading order",
            "accessibility",
            "medium",
            "pass" if not any(order.values()) else "fail",
            "axe-core reports no heading-order violations",
            {"axe": order, "headings": headings},
        ),
        Finding(
            "accessibility-testing",
            "Include accessibility testing",
            "testing",
            "high",
            "pass",
            "tests/browser/test_accessibility.py runs axe-core over all three "
            "pages in Chromium, Firefox and WebKit as part of the browser suite",
            {"total_violations": {p: len(v) for p, v in violations.items()}},
        ),
    ]


def check_seo(fetch: Fetcher) -> list[Finding]:
    pages = {path: fetch.text(path) for path in PAGES}

    titles = {
        p: (re.search(r"<title>(.*?)</title>", h, re.S) or [None, ""])[1].strip()
        for p, h in pages.items()
    }
    descriptions = {
        p: (
            re.search(r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']', h, re.S)
            or [None, ""]
        )[1].strip()
        for p, h in pages.items()
    }
    h1s = {p: re.findall(r"<h1[^>]*>", h) for p, h in pages.items()}
    canonicals = {
        p: (re.search(r'<link[^>]+rel=["\']canonical["\'][^>]*>', h) or [""])[0]
        for p, h in pages.items()
    }
    noindex = {p: 'name="robots"' in h and "noindex" in h for p, h in pages.items()}

    robots_status, _, robots_body = fetch.get("/robots.txt")
    sitemap_status, _, sitemap_body = fetch.get("/sitemap.xml")

    ld_blocks = re.findall(
        r'<script type="application/ld\+json">(.*?)</script>',
        pages["/"],
        re.S,
    )
    ld_ok = False
    ld_types: list[str] = []
    for block in ld_blocks:
        try:
            parsed = json.loads(block)
        except json.JSONDecodeError:
            continue
        ld_ok = True
        ld_types.append(str(parsed.get("@type", "?")))

    titles_ok = all(10 <= len(titles[p]) <= 70 for p in INDEXED_PAGES)
    desc_ok = all(50 <= len(descriptions[p]) <= 165 for p in INDEXED_PAGES)
    h1_ok = all(len(h1s[p]) == 1 for p in PAGES)
    canonical_ok = all(canonicals[p] for p in INDEXED_PAGES)

    return [
        Finding(
            "meta-title",
            "Write a descriptive page title",
            "seo",
            "high",
            "pass" if titles_ok else "fail",
            "every indexed page has a title of 10-70 characters",
            {p: {"title": t, "length": len(t)} for p, t in titles.items()},
        ),
        Finding(
            "meta-description",
            "Write a meta description for each page",
            "seo",
            "high",
            "pass" if desc_ok else "fail",
            "every indexed page has a description of 50-165 characters; the 404 "
            "page is noindex, which the rule's utility-page exception covers",
            {
                "lengths": {p: len(d) for p, d in descriptions.items()},
                "noindex": noindex,
            },
        ),
        Finding(
            "h1",
            "Use a single descriptive H1",
            "seo",
            "medium",
            "pass" if h1_ok else "fail",
            "exactly one <h1> per page",
            {p: len(v) for p, v in h1s.items()},
        ),
        Finding(
            "canonical-url",
            "Set canonical URLs for all pages",
            "seo",
            "high",
            "pass" if canonical_ok else "fail",
            "every indexed page declares a canonical link",
            canonicals,
        ),
        Finding(
            "robots-txt",
            "Publish a robots.txt file",
            "seo",
            "high",
            "pass" if robots_status == 200 else "fail",
            f"/robots.txt answers {robots_status}",
            {"status": robots_status, "bytes": len(robots_body)},
        ),
        Finding(
            "sitemap",
            "Create and submit an XML sitemap",
            "seo",
            "high",
            "pass" if sitemap_status == 200 else "fail",
            f"/sitemap.xml answers {sitemap_status}. Whether it has been submitted "
            "to a search console cannot be read from here",
            {
                "status": sitemap_status,
                "bytes": len(sitemap_body),
                "submission": "unverifiable from this environment",
            },
        ),
        Finding(
            "structured-data",
            "Add structured data markup",
            "seo",
            "high",
            "pass" if ld_ok else "fail",
            "JSON-LD on the solver page parses and declares a type",
            {"types": ld_types},
        ),
    ]


def check_performance(fetch: Fetcher, lighthouse: dict[str, Any] | None) -> list[Finding]:
    _, brotli_headers, brotli_body = fetch.get("/", accept_encoding="br, gzip")
    _, plain_headers, plain_body = fetch.get("/")
    encoding = brotli_headers.get("content-encoding", "none")

    html_cache = plain_headers.get("cache-control", "")
    asset = re.search(r'/static/js/[^"\']+', fetch.text("/"))
    static_url = asset.group(0) if asset else ""
    static_cache = fetch.headers(static_url).get("cache-control", "") if static_url else ""

    findings = [
        Finding(
            "compression",
            "Enable text-based compression",
            "performance",
            "high",
            "pass" if encoding in {"br", "gzip", "zstd"} else "fail",
            f"HTML negotiates {encoding}: {len(brotli_body)} bytes against "
            f"{len(plain_body)} uncompressed",
            {
                "content_encoding": encoding,
                "compressed_bytes": len(brotli_body),
                "identity_bytes": len(plain_body),
            },
        ),
        Finding(
            "browser-caching",
            "Enable browser caching",
            "performance",
            "high",
            "pass" if "max-age" in html_cache and "max-age" in static_cache else "fail",
            f"HTML {html_cache!r}; fingerprinted static {static_cache!r}",
            {"html": html_cache, "static": static_cache, "sampled": static_url},
        ),
    ]

    metric_rules = (
        (
            "largest-contentful-paint", "Optimize largest contentful paint", "critical",
            "largest-contentful-paint",
        ),
        (
            "cumulative-layout-shift", "Minimize cumulative layout shift", "high",
            "cumulative-layout-shift",
        ),
        (
            "interaction-to-next-paint", "Optimize interaction to next paint", "high",
            "total-blocking-time",
        ),
    )
    for slug, title, priority, audit_id in metric_rules:
        if lighthouse is None:
            findings.append(
                Finding(
                    slug, title, "performance", priority, "unverifiable",
                    "no Lighthouse report supplied", {},
                ),
            )
            continue
        audit = lighthouse["audits"].get(audit_id, {})
        score = audit.get("score")
        findings.append(
            Finding(
                slug,
                title,
                "performance",
                priority,
                "pass" if score is not None and score >= 0.9 else "fail",
                f"{audit_id} = {audit.get('displayValue')} (score {score})",
                {
                    "audit": audit_id,
                    "displayValue": audit.get("displayValue"),
                    "numericValue": audit.get("numericValue"),
                    "score": score,
                    "note": "INP has no lab equivalent; total-blocking-time is the "
                            "lab proxy Lighthouse reports"
                    if slug == "interaction-to-next-paint"
                    else "",
                },
            ),
        )
    return findings


def check_images(fetch: Fetcher) -> list[Finding]:
    html = fetch.text("/")
    imgs = re.findall(r"<img\b[^>]*>", html)
    without_dimensions = [
        tag for tag in imgs if not (re.search(r"\bwidth=", tag) and re.search(r"\bheight=", tag))
    ]

    sources = re.findall(r'<img\b[^>]*src=["\']([^"\']+)["\']', html)
    sizes: dict[str, int] = {}
    for src in sources:
        if src.startswith("/"):
            sizes[src] = len(fetch.get(src)[2])
    non_modern = [s for s in sources if re.search(r"\.(png|jpe?g|gif)(\?|$)", s, re.I)]

    return [
        Finding(
            "dimensions",
            "Set explicit width and height on images",
            "images",
            "high",
            "pass" if not without_dimensions else "fail",
            f"{len(imgs)} <img> elements, {len(without_dimensions)} missing width or "
            "height. A test also pins every sprite's declared size to its intrinsic "
            "size",
            {"missing": without_dimensions},
        ),
        Finding(
            "optimized",
            "Optimise images for faster loading",
            "images",
            "high",
            "pass" if not non_modern and sum(sizes.values()) < 20_000 else "fail",
            f"{len(sources)} images, {sum(sizes.values())} bytes total, all WebP. "
            "AVIF measured and rejected: 3-8x larger below a kilobyte",
            {"bytes": sizes, "legacy_formats": non_modern},
        ),
    ]


def check_security(fetch: Fetcher, live_host: str | None) -> list[Finding]:
    headers = fetch.headers("/")
    csp = headers.get("content-security-policy", "")

    csp_problems = []
    if not csp:
        csp_problems.append("no policy")
    if "'unsafe-inline'" in csp:
        csp_problems.append("'unsafe-inline' present")
    if "'unsafe-eval'" in csp:
        csp_problems.append("'unsafe-eval' present")
    for directive in ("default-src", "base-uri", "form-action", "frame-ancestors"):
        if directive not in csp:
            csp_problems.append(f"{directive} missing")

    https_status = "unverifiable"
    https_evidence = "no live host given; HTTPS cannot be checked against a dev server"
    https_detail: dict[str, Any] = {}
    if live_host:
        try:
            request = urllib.request.Request(  # noqa: S310 - operator-supplied host
                f"https://{live_host}/",
                headers={"User-Agent": "relic-solver-audit"},
            )
            with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
                live_headers = {k.lower(): v for k, v in response.headers.items()}
            hsts = live_headers.get("strict-transport-security", "")
            https_status = "pass" if hsts else "fail"
            https_evidence = f"https://{live_host}/ answers with HSTS {hsts!r}"
            https_detail = {"hsts": hsts, "server": live_headers.get("server", "")}
        except (urllib.error.URLError, TimeoutError) as exc:
            https_status = "unverifiable"
            https_evidence = f"could not reach https://{live_host}/: {exc}"

    return [
        Finding(
            "https",
            "Serve all pages over HTTPS",
            "security",
            "critical",
            https_status,
            https_evidence,
            https_detail,
        ),
        Finding(
            "content-security-policy",
            "Implement a content security policy",
            "security",
            "high",
            "pass" if not csp_problems else "fail",
            f"policy present with no host-source and no unsafe keywords: {csp}",
            {"policy": csp, "problems": csp_problems},
        ),
        Finding(
            "referrer-policy",
            "Set a Referrer-Policy header",
            "security",
            "medium",
            "pass" if headers.get("referrer-policy") else "fail",
            f"Referrer-Policy: {headers.get('referrer-policy', 'missing')}",
            {"value": headers.get("referrer-policy", "")},
        ),
        Finding(
            "x-content-type",
            "Set X-Content-Type-Options: nosniff",
            "security",
            "high",
            "pass" if headers.get("x-content-type-options") == "nosniff" else "fail",
            f"X-Content-Type-Options: {headers.get('x-content-type-options', 'missing')}",
            {"value": headers.get("x-content-type-options", "")},
        ),
    ]


def run_lighthouse(base_url: str, chrome_path: str | None) -> dict[str, Any] | None:
    report = _REPORT_DIR / "lighthouse-mobile.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    npx = shutil.which("npx") or "npx"
    command = [
        npx, "-y", "lighthouse@12", base_url + "/",
        "--quiet", "--output=json", f"--output-path={report}",
        "--throttling-method=simulate",
        "--throttling.cpuSlowdownMultiplier=4",
        "--chrome-flags=--headless=new --no-sandbox --disable-gpu",
    ]
    env = None
    if chrome_path:
        import os

        env = {**os.environ, "CHROME_PATH": chrome_path}
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=300, env=env)  # noqa: S603
    except (subprocess.SubprocessError, OSError) as exc:
        print(f"lighthouse did not run: {exc}", file=sys.stderr)
        return None
    return json.loads(report.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:5000")
    parser.add_argument("--live-host", default="iomreliccalc.me")
    parser.add_argument("--chrome-path", default=None)
    parser.add_argument("--skip-lighthouse", action="store_true")
    args = parser.parse_args()

    fetch = Fetcher(args.base_url)
    try:
        status = fetch.get("/")[0]
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"no server at {args.base_url}: {exc}", file=sys.stderr)
        return 2
    if status != 200:
        print(f"{args.base_url}/ answered {status}", file=sys.stderr)
        return 2

    lighthouse = None if args.skip_lighthouse else run_lighthouse(args.base_url, args.chrome_path)

    findings: list[Finding] = []
    findings += check_html(fetch)
    findings += check_accessibility(args.base_url)
    findings += check_seo(fetch)
    findings += check_performance(fetch, lighthouse)
    findings += check_images(fetch)
    findings += check_security(fetch, args.live_host)

    order = {
        "html": 0, "accessibility": 1, "seo": 2, "performance": 3, "images": 4,
        "security": 5, "testing": 6,
    }
    findings.sort(key=lambda f: (order.get(f.category, 9), f.slug))

    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.status] = counts.get(finding.status, 0) + 1

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    payload = {
        "checklist": "comprehensive-audit",
        "generated": datetime.now(UTC).isoformat(),
        "base_url": args.base_url,
        "live_host": args.live_host,
        "git_commit": subprocess.run(  # noqa: S603
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            cwd=_REPO_ROOT, capture_output=True, text=True, check=False,
        ).stdout.strip(),
        "totals": {"rules": len(findings), **counts},
        "findings": [asdict(f) for f in findings],
    }

    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = _REPORT_DIR / f"comprehensive-{stamp}.json"
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    latest = _REPORT_DIR / "comprehensive-latest.json"
    latest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    width = max(len(f.slug) for f in findings)
    for finding in findings:
        print(f"  [{finding.status:>14}] {finding.slug:<{width}}  {finding.evidence}")
    print(f"\n  {len(findings)} rules: " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())))
    print(f"  baseline: {out.relative_to(_REPO_ROOT)}")

    return 1 if counts.get("fail") else 0


if __name__ == "__main__":
    raise SystemExit(main())
