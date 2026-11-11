## v5.0.0 (2026-11-11)

## v4.1.0 (2026-10-25)

### Feat

- **security**: publish a signed RFC 9116 security.txt

### Fix

- **ci**: force the deploy push to Heroku

### Refactor

- **web**: keep template comments out of the served HTML

## v3.2.0 (2026-10-24)

### Feat

- **web**: add release notes, and fix two layout faults they would have shown
- **ops**: add checks for the Cloudflare cutover and its edge ranges
- **web**: add a Discord link and Ko-fi's official button to the footer
- **config**: raise the divine relic cap maximum to 36
- **a11y**: associate the field help and validate before submitting
- **privacy**: expire the saved inputs and give them an off switch
- **privacy**: drop the analytics pipeline and publish a privacy page
- **web**: mark the GitHub link with the official octocat
- **web**: show the gem sprite beside the gem count
- **seo**: name the page topic, the author and the cited source
- **web**: add a branded 404, an apple-touch-icon and a descriptive title
- **web**: add canonical, structured data, manifest and font preloads

### Fix

- **ci**: keep the browser suite out of the deploy job
- **hooks**: clear two stale entries from the secrets baseline
- **types**: satisfy the checks that only run on push
- **deps**: declare fontTools and Pillow instead of borrowing them
- **security**: count real visitors, and make the CSP survive an edge cache
- **ops**: lower the solve ceiling below what a proxy will wait for
- **web**: fingerprint static assets by content, not release version
- **js**: harden the client against stalls, leaks and malformed frames
- **web**: cap the cache life of the root-served static files
- **web**: name the WebP sprites .webp and freeze versioned static assets
- **a11y**: give the noscript notice a readable panel

### Perf

- **web**: subset the fonts and ship the small favicon sizes
- **images**: convert the last PNGs to WebP and render sprites 1:1

## v3.1.0 (2026-10-22)

### Feat

- **cache**: recover from a Redis outage without a restart
- **api**: return JSON errors to API callers
- **health**: distinguish a broken Redis from an absent one
- **webapp**: expose game constants to templates via context processor
- **justfile**: add docker recipes and import the shared parent justfile

### Fix

- **types**: import time and redis directly in the reconnect tests
- **deploy**: forward SIGTERM to gunicorn and honour WEB_CONCURRENCY
- **types**: pin the Accept header lookup before comparing
- **ui**: show an error when the stream ends without a result
- **docker**: repair the image build, drop root, install from the lockfile
- **deploy**: reconcile the solver deadline with the worker timeout
- **security**: cap the request body size
- **limiter**: count rate limits in Redis, not per worker
- **solve**: report catastrophic solver failures instead of truncating
- **logging**: configure logging so INFO records actually emit
- **security**: explicitly disable the legacy XSS Auditor
- **security**: add Subresource Integrity to the jsDelivr resources
- **types**: drop unused type: ignore on the ProxyFix assignment
- **security**: redirect HTTP to HTTPS behind Heroku's router

### Refactor

- **lint**: run oxlint from its standalone binary
- **config**: parse runtime settings once, and validate them

### Perf

- **web**: serve brotli 9 and stop shipping static files uncompressed

## v3.0.0 (2026-08-03)

### BREAKING CHANGE

- fixes not getting and inputting beyond 26 in the input fields and also fixes tests breaking

### Fix

- **Relic-Cap**: Changed the relic cap from 26 to 32 based on the new Update 2.2 - Arcanist
- **pre-commit**: remove explicit docformatter config arg

## v2.3.9 (2026-04-25)

### Fix

- **dasdasd**: asd

## v2.3.8 (2026-04-25)

### Fix

- **asdasdadas**: asdasd

## v2.3.7 (2026-04-25)

### Fix

- **graaah**: ashdadasd

## v2.3.6 (2026-04-25)

### Fix

- **fix**: node_module bs

## v2.3.5 (2026-04-25)

### Fix

- **permissions**: manual perm fix

## v2.3.4 (2026-04-25)

### Fix

- **ci/cd-pipeline**: fixed executable permissioin issue on linux with github actions, changed to npm internal

## v2.3.3 (2026-04-25)

### Fix

- **fixed-precommit**: fixed it

## v2.3.2 (2026-04-25)

### Fix

- **fix-for-breaking-bumps**: yup

## v2.3.1 (2026-04-25)

### Fix

- **broken-visualize-report**: fixed with creating reports dir via workflow

## v2.3.0 (2026-04-25)

### Feat

- **updated-relic-cap**: updated relic cap
- **python-version,-relic-cap**: updated python version to 3.14 and updated relci cap to current 26

### Fix

- **pre-commit**: fixed detect-secrets
- **npm**: fixed not having npm stuff added
- removed weekly report
- removed weekly report
- updated relic cap in html input limit
- updated relic cap in html input limit
- python-version and relic-cap

## v2.2.0 (2026-02-19)

## v2.1.0 (2026-02-19)

### Feat

- **analytics**: add weekly report pipeline, CI visualizations, and security fixes

### Fix

- **deleted-broken-workflow**: removed workflow of qyron that was not needed and broken
- **security**: fix detect-secrets exclude pattern for Windows paths
- **security**: exclude generated weekly report files from detect-secrets scan
- **ci**: restrict CSS build to branch pushes only

## v2.0.1 (2026-02-15)

## v2.0.0 (2026-02-15)

### Feat

- **solver**: add NumPy-vectorized solver with 211x speedup on worst case
- **cache**: add Redis caching layer for deterministic solver results
- v2.0 solver rewrite, frontend performance overhaul, and tooling expansion
- google search icon fix
- google search icon fix
- google search icon fix
- fixed wrong http being sent to sentry, fixed sentry and tested log use. removed unused logging. added web vitals
- Added sentry systems, added logging and anonymous data sending for improvements and analysis.
- Added sentry systems, added logging and anonymous data sending for improvements and analysis.
- Added sentry systems, added logging and anonymous data sending for improvements and analysis.
- 3 new security and optimization libs
- robots.txt added + sitemap.xml added
- production ready
- production ready
- production ready
- production ready
- production ready
- production ready
- production ready
- production ready
- production ready
- **ui**: redesign frontend with pixel art theme and 2x2 grid layout
- implement Markov chain solver, tests, and project infrastructure
- initial relic solver implementation
- initial relic solver implementation

### Fix

- **tests**: reduce relic_cap_very_large from 100 to 30
- **tests**: remove unused type: ignore comment
- reoganized todo
- **deps**: trim production dependencies to flask, gunicorn, scipy
- **circleci**: pin Python 3.13.11 image and skip doctoc in CI

### Refactor

- separate solver library from webapp with src/ layout
- clean up project structure and fix .gitignore
- **local-only-folders**: removed folders that were missing in gitignore
