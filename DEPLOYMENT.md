# Deployment

This document covers running Relic Solver locally and deploying to production.

The official site is [iomreliccalc.me](https://iomreliccalc.me), hosted on
[Heroku](https://www.heroku.com/).

- [Local Development](#local-development)
- [Production (Heroku)](#production-heroku)
  - [What Runs on Heroku](#what-runs-on-heroku)
  - [How Deployment Works](#how-deployment-works)
  - [Heroku CLI Commands](#heroku-cli-commands)
- [Environment Variables](#environment-variables)

## Local Development

The Flask dev server is all you need for local work. No Redis or gunicorn
required - the app runs fine without them.

```bash
# Dev server with hot reload
uv run flask run --debug   # or: just dev

# Without debug mode
uv run flask run

# Direct Python entry point
uv run python app.py
```

The dev server starts on `http://127.0.0.1:5000` by default.

**Local production-like server** (Windows): the `Procfile.windows` uses
[waitress](https://docs.pylonsproject.org/projects/waitress/) instead of
gunicorn (which does not support Windows):

```bash
# Via Heroku CLI
heroku local -f Procfile.windows   # or: just heroku-dev

# Or directly
uv run waitress-serve --host=127.0.0.1 --port=8080 --no-ipv6 app:app
```

For environment variable setup (Redis, CORS), see
[CONTRIBUTING.md](CONTRIBUTING.md#environment-variables).

## Production (Heroku)

### What Runs on Heroku

- **Web**: Eco dyno (~$5/mo), `Procfile` runs `gunicorn --timeout 620 --graceful-timeout 30 --preload --workers 2 app:app`
- **Redis**: Redis Cloud add-on, `REDISCLOUD_URL` set automatically (falls back to `REDIS_URL`)
- **Python version**: detected from `pyproject.toml` (no `runtime.txt` needed)
- **Domain**: [iomreliccalc.me](https://iomreliccalc.me)

### Timeouts and Restarts

A single solve is capped at `SOLVE_MAX_SECONDS` (600s) in
[`config.py`](src/relic_solver/config.py), which sits below gunicorn's
`--timeout` (620s) so the solver always reaches its own deadline first and can
send the client a proper error frame. Tests read `Procfile` and `Dockerfile` to
keep the two numbers in step -- change one and the suite will say so.

Heroku cycles dynos roughly every 24 hours. On `SIGTERM` gunicorn stops
accepting connections and kills the worker after `--graceful-timeout` (30s), so
a solve that is streaming at that moment has its NDJSON response closed without
a final `result` or `error` frame. This is accepted rather than handled: the
window is small and covering it properly would mean stalling every deploy until
in-flight solves drain.

The frontend surfaces this: `solver.js` tracks whether a terminal `result` or
`error` frame arrived, and a stream that ends without one resets the progress
bar and shows a retry message rather than spinning indefinitely.

### How Deployment Works

GitHub Actions CI deploys automatically after tests pass on `main` (see
[`deploy.yml`](.github/workflows/deploy.yml)). The workflow runs the test
suite (excluding benchmarks), then pushes to the Heroku git remote.

Manual deployment is also possible:

```
git push heroku main
  -> detects Python (via pyproject.toml)
  -> installs deps
  -> builds slug (compressed app snapshot)
  -> starts dyno via Procfile command
  -> live at iomreliccalc.me
```

<details>
<summary><b>Heroku CLI Commands</b></summary>

```bash
# Login
heroku login

# Create an app
heroku create your-app-name

# Deploy
git push heroku main

# Add Redis (Redis Cloud recommended)
heroku addons:create rediscloud:30

# Set environment variables
heroku config:set FORCE_HTTPS=1

# View logs
heroku logs --tail

# Open the app in browser
heroku open

# Check dyno status
heroku ps
```

</details>

## Environment Variables

Set these in Heroku via `heroku config:set` or the dashboard. For local
development, all are optional - see
[CONTRIBUTING.md](CONTRIBUTING.md#environment-variables) for `.env` setup.

| Variable | Purpose | Default |
|----------|---------|---------|
| `REDISCLOUD_URL` | Redis Cloud connection string (set by the add-on) | none (caching disabled) |
| `REDIS_URL` | Fallback Redis URL | none |
| `CORS_ORIGIN` | Allowed CORS origin | `*` |
| `FORCE_HTTPS` | Redirect plain HTTP to HTTPS with a 308 (`1`, `true` or `yes`) | unset (no redirect) |
