import? '../../justfile'

# Relic Solver - development task runner
# Run `just` with no arguments to see all available recipes.
# use PowerShell instead of sh:
set shell := ["powershell.exe", "-c"]

set dotenv-load := false

# Default: list available recipes
default:
    @just --list

# ---------------------------------------------------------------------------
# Development
# ---------------------------------------------------------------------------

# Start Flask dev server with debug mode
dev: build
    uv run flask run --debug

# Start Heroku local dev/release environment
heroku-dev:
    heroku local -f .\Procfile.windows

# Sync all dependencies from lockfile
sync:
    uv sync
    npm install

# Open a Rich-enabled Python REPL
repl:
    uv run python -i -c "from rich import pretty, traceback; pretty.install(); traceback.install(show_locals=True); print('Rich REPL ready')"

# Run the cProfile profiler on a sample solve
profile:
    uv run python -m relic_solver

# Memory profiling with tracemalloc (add --heavy for worst-case)
profile-mem *args:
    uv run python scripts/profile_memory.py {{ args }}

# Prewarm Redis cache (add --dry-run, --tier 1|2, --workers N)
prewarm *args:
    uv run python scripts/prewarm_cache.py {{ args }}

# Flush all keys from the Redis cache
cache-flush:
    #!powershell
    $url = if ($env:REDISCLOUD_URL) { $env:REDISCLOUD_URL } elseif ($env:REDIS_URL) { $env:REDIS_URL } else { (heroku config:get REDISCLOUD_URL -a relic-solver) }
    if (-not $url) { Write-Error "No Redis URL found"; exit 1 }
    uv run python -c "import redis; rc = redis.Redis.from_url('$url', decode_responses=True); n = rc.dbsize(); rc.flushdb(); print(f'Flushed {n} keys')"

# Minify CSS
build-css:
    npx postcss style.css -o src/webapp/static/css/style.min.css --config ./postcss.config.js --no-map

# Minify the shipped JavaScript (sources stay beside the artifacts)
build-js:
    npm run build-js

# Both build artifacts: style.min.css and the three .min.js files
build: build-css build-js

# ---------------------------------------------------------------------------
# Analytics & Data
# ---------------------------------------------------------------------------

# Export analytics + cache CSVs to reports/ with today's date (YYYYMMDD)
getdata:
    #!powershell
    $date = Get-Date -Format "yyyyMMdd"
    New-Item -ItemType Directory -Force -Path reports | Out-Null
    uv run python scripts/export_analytics.py --mode analytics -o "reports/analytics_$date.csv"
    uv run python scripts/export_analytics.py --mode cache -o "reports/cache_$date.csv"
    Write-Host "Exported to reports/analytics_$date.csv and reports/cache_$date.csv"

# Print aggregate stats from merged analytics CSV (pass a different file as arg, e.g. data.csv)
stats *args:
    uv run python scripts/aggregate_stats.py {{ args }}

# Accuracy chart: computed vs known exact expected values
viz-accuracy *args:
    uv run python scripts/visualize_test_accuracy.py {{ args }}

# Cross-validation chart: NumPy vs dict solver agreement across 13 cases
viz-cross-val *args:
    uv run python scripts/visualize_cross_validation.py {{ args }}

# Benchmark timing chart from pytest-benchmark JSON (auto-finds latest in .benchmarks/)
viz-bench *args:
    uv run python scripts/visualize_benchmarks.py {{ args }}

# Test suite summary from pytest JSON report (run tests with --json-report first)
viz-tests *args:
    uv run python scripts/visualize_test_suite.py {{ args }}

# Merge all dated analytics/cache CSVs in reports/ into merged files (removes duplicate rows)
datamerge:
    uv run python scripts/merge_csv.py --dir reports --pattern "analytics_*.csv" -o reports/analytics_merged.csv
    uv run python scripts/merge_csv.py --dir reports --pattern "cache_*.csv" -o reports/cache_merged.csv

# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------

# Run all tests (default: compact sugar output)
test *args:
    uv run pytest {{ args }}

# Run tests in verbose mode
test-v *args:
    uv run pytest -v {{ args }}

# Run tests, stop on first failure
test-x *args:
    uv run pytest -x {{ args }}

# Run only unit tests
test-unit:
    uv run pytest tests/unit/

# Run only integration tests
test-int:
    uv run pytest tests/integration/

# Unit-test the page's pure JS helpers (node:test, no dependencies)
test-js:
    npm run test-js

# Download the Playwright engines (one-off, a few hundred MB)
browsers:
    uv run playwright install chromium firefox webkit

# Run the browser suite on one engine (default chromium; needs `just browsers`)
test-browser engine="chromium":
    uv run pytest tests/browser -m browser --no-cov --browser {{ engine }}

# Run the browser suite on all three engines - this is the cross-browser check
test-browser-all:
    uv run pytest tests/browser -m browser --no-cov         --browser chromium --browser firefox --browser webkit

# Everything: Python, JS helpers, then the browser suite
test-all:
    uv run pytest
    npm run test-js
    uv run pytest tests/browser -m browser --no-cov --browser chromium

# Run benchmarks (disabled by default in addopts)
bench:
    uv run pytest --benchmark-enable --benchmark-only --no-cov -v

# Run benchmarks and save as named baseline (default: "baseline")
bench-save name="baseline":
    uv run pytest --benchmark-enable --benchmark-only --no-cov --benchmark-save={{ name }} -v

# Run benchmarks and compare against the most recent saved baseline
bench-compare:
    uv run pytest --benchmark-enable --benchmark-only --no-cov --benchmark-compare -v

# Open the HTML coverage report in the browser
coverage:
    uv run pytest -q
    start tests/reports/htmlcov/index.html

# ---------------------------------------------------------------------------
# Linting & Type Checking
# ---------------------------------------------------------------------------

pre-commit:
    uv run pre-commit run --all-files

# Run all pre-commit hooks
lint:
    uv run pre-commit run --all-files

# Lint the shipped JavaScript.
#
# Needs the oxlint binary on PATH. It is a standalone executable -- no node,
# no npm. To install or upgrade it on Linux (keep the version in step with
# the one pinned in ci-pr.yml):
#
#   v=1.84.0
#   curl -sSfL "https://github.com/oxc-project/oxc/releases/download/apps_v$v/oxlint-x86_64-unknown-linux-gnu.tar.gz" \
#     | tar xz -C /tmp
#   install -m 0755 /tmp/oxlint-x86_64-unknown-linux-gnu ~/.local/bin/oxlint
lint-js:
    uv run pre-commit run oxlint --all-files

# Run mypy on a specific file or the whole project
mypy *files:
    uv run pre-commit run mypy --files {{ if files == "" { "src/relic_solver/solver.py src/relic_solver/config.py src/relic_solver/__init__.py app.py" } else { files } }}

# Run formatters only (trailing commas, pyupgrade, docformatter)
format:
    uv run pre-commit run add-trailing-comma --all-files
    uv run pre-commit run pyupgrade --all-files
    uv run pre-commit run docformatter --all-files

# ---------------------------------------------------------------------------
# Git & Deployment
# ---------------------------------------------------------------------------

# Generate THIRD_PARTY_LICENSES from installed packages
tpl:
    uv run pip-licenses --output-file=THIRD_PARTY_LICENSES --with-license-file --no-license-path --with-notice-file --order=license --from=mixed -f plain-vertical

# Check for accidentally committed build artifacts
check-artifacts:
    #!powershell
    $patterns = @("__pycache__", "*.pyc", "*.pyo", ".coverage", "htmlcov/", ".mypy_cache/", ".pytest_cache/", ".benchmarks/", "*.egg-info/")
    $found = @()
    foreach ($p in $patterns) { $matches = git ls-files $p 2>$null; if ($matches) { $found += $matches } }
    if ($found.Count -gt 0) { Write-Host "Build artifacts found in tracked files:" -ForegroundColor Red; $found | ForEach-Object { Write-Host "  $_" }; exit 1 }
    Write-Host "No build artifacts in tracked files." -ForegroundColor Green

# Keep the subject SHORT at its prompt. A prompt input is one line wide, so
# long text typed or pasted into one picks up the terminal's wrap points as
# real newlines, and commitizen then rejects the message: the subject must
# stay a single line. Write long bodies with "just commit-edit" instead.

# Conventional commit with commitizen
commit:
    uv run cz commit --no-retry

# Same prompts, then your editor opens on the message for a long body
commit-edit:
    uv run cz commit --no-retry --edit

# Push to GitHub origin (current branch)
push-origin:
    git push origin

# Full deploy: stage all, commitizen commit, push to origin
deploy:
    git add .
    uv run cz commit --no-retry
    git push origin main

# Bump version (auto from conventional commits), push commits + tag.
# Force increment: just release patch | minor | major
release increment="":
    uv run cz bump {{ if increment != "" { "--increment " + uppercase(increment) } else { "" } }}
    git push origin main --follow-tags

# Show git status + recent log
@status:
    git status -sb
    Write-Host "---"
    git log --oneline -5

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

# Remove generated artifacts
# Clean for Posix Systems (Linux, MacOS)
clean-posix:
    #!/bin/sh
    set -e

    paths=".coverage .benchmarks __pycache__ .mypy_cache .pytest_cache \
    src/relic_solver/__pycache__ tests/__pycache__ tests/unit/__pycache__ tests/integration/__pycache__ \
    tests/reports/htmlcov"

    for p in $paths; do
        [ -e "$p" ] && rm -rf "$p"
    done

    # Remove all markdown files in tests/reports
    find tests/reports -maxdepth 1 -name "*.md" -type f -exec rm -f {} +

    echo "Cleaned."

# Clean for Windows
clean-windows:
    #!powershell
    $ErrorActionPreference = 'SilentlyContinue'
    $paths = @(
        '.coverage', '.benchmarks', '__pycache__', '.mypy_cache', '.pytest_cache',
        'src/relic_solver/__pycache__', 'tests/__pycache__', 'tests/unit/__pycache__', 'tests/integration/__pycache__',
        'tests/reports/htmlcov'
    )
    foreach ($p in $paths) { if (Test-Path $p) { Remove-Item -Recurse -Force $p } }
    Get-ChildItem tests/reports/*.md -ErrorAction SilentlyContinue | Remove-Item -Force
    Write-Host "Cleaned."

# ---------------------------------------------------------------------------
# Docker (run from WSL)
# ---------------------------------------------------------------------------

# Start Flask + Redis + Dozzle in the background
docker-up:
    #!/usr/bin/env bash
    set -euo pipefail
    docker compose up --build -d

# Stop the stack (keeps the redis-data volume intact)
docker-down:
    #!/usr/bin/env bash
    set -euo pipefail
    docker compose down

# Tail logs from all three services
docker-logs:
    #!/usr/bin/env bash
    set -euo pipefail
    docker compose logs -f

# Stop the stack AND wipe the redis-data volume (fresh cache on next start)
docker-reset:
    #!/usr/bin/env bash
    set -euo pipefail
    docker compose down -v

# Re-subset the web fonts from assets/font-sources/ into the served fonts dir
subset-fonts:
    uv run python scripts/subset_fonts.py

# Regenerate the 16x16 / 32x32 favicons and the multi-size favicon.ico
favicons:
    uv run python scripts/make_favicons.py

# ---------------------------------------------------------------------------
# Security contact (RFC 9116)
# ---------------------------------------------------------------------------

# The key that signs security.txt and is published as pgp-key.txt. Named by
# full fingerprint so a second key with the same uid cannot be picked by
# accident.
SECURITY_TXT_KEY := "EED2386B40494CDCF8B61B4CDDD85342D44D6BE0" # pragma: allowlist secret

WELL_KNOWN := "src/webapp/static/.well-known"

# Everything in scripts/security.txt.in is signed and therefore published,
# comments included, so that file carries no maintainer notes. The ones that
# would have gone there:
#
#   - Edit scripts/security.txt.in, never the signed output. An edit to the
#     output breaks the signature.
#   - Expires must stay under a year from the day it is signed (RFC 9116
#     section 2.5.5). A test fails once it is 30 days out, which is the
#     reminder to re-sign.
#   - Contact is read in order of preference (section 2.5.3). The advisory
#     form comes first because the alias behind the mailto sits on a plan
#     with a monthly byte budget and rejects mail outright once it is spent,
#     which is the wrong failure for a security report. Do not write that
#     reason into the .in file: it tells a stranger how to shut the mailbox.

# Export the public key a reporter encrypts their report to
export-pgp-key:
    gpg --yes --armor --output {{WELL_KNOWN}}/pgp-key.txt --export {{SECURITY_TXT_KEY}}

# Clearsign scripts/security.txt.in into the file the site serves
sign-security-txt:
    gpg --yes --local-user {{SECURITY_TXT_KEY}} --digest-algo SHA512 --clearsign --output {{WELL_KNOWN}}/security.txt scripts/security.txt.in

# Rebuild and verify both halves after editing the source or rotating the key
security-txt: export-pgp-key sign-security-txt
    gpg --verify {{WELL_KNOWN}}/security.txt

# Check the Cloudflare cutover: delegation, zone records and edge headers
check-dns:
    @pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/check-dns.ps1

# Same checks from a POSIX shell (WSL, git-bash, CI); needs dig for the DNS half
check-dns-sh:
    @bash scripts/check-dns.sh

# Compare the Cloudflare edge ranges in app.py against Cloudflare's live list
check-cloudflare-ips:
    @uv run python scripts/check_cloudflare_ips.py

# Walk the comprehensive Front-End Checklist and write a JSON baseline
audit:
    @uv run python scripts/audit_comprehensive.py --chrome-path "{{env_var_or_default('CHROME_PATH', 'C:/Users/zaube/AppData/Local/ms-playwright/chromium-1248/chrome-win64/chrome.exe')}}"
