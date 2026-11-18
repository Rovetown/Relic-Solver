import base64
import functools
import hashlib
import ipaddress
import json
import logging
import math
import os
import queue
import re
import secrets
import sys
import threading
import time
from collections.abc import Generator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import redis
from flask import (
    Flask,
    Response,
    g,
    has_request_context,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_from_directory,
    stream_with_context,
    url_for,
)
from flask_compress import Compress
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.exceptions import HTTPException, InternalServerError
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.wrappers import Response as WerkzeugResponse

from relic_solver import expected_gems, expected_rerolls, solve
from relic_solver._version import __version__
from relic_solver.config import (
    COST_PER_REROLL,
    DEFAULT_RELIC_CAP,
    MAX_OBELISK_LEVEL,
    MAX_RELIC_CAP,
    MAX_REQUEST_BYTES,
    MIN_OBELISK_LEVEL,
    MIN_RELIC_CAP,
    NUM_RELIC_TYPES,
    OBELISK_D2_THRESHOLD,
    OBELISK_D3_THRESHOLD,
    OBELISK_D4_THRESHOLD,
    OBELISK_D5_THRESHOLD,
    OBELISK_LEVEL_BANDS,
    RATE_LIMIT_DEFAULT,
    RATE_LIMIT_SOLVE,
    SOLVE_MAX_SECONDS,
)

solver_version = __version__

_webapp = Path(__file__).resolve().parent / "src" / "webapp"


_TRUE_TOKENS = frozenset({"1", "true", "yes", "on"})
_FALSE_TOKENS = frozenset({"0", "false", "no", "off", ""})
_REDIS_SCHEMES = ("redis://", "rediss://")


@dataclass(frozen=True, slots=True)
class Settings:
    cors_origin: str
    force_https: bool
    redis_url: str | None
    log_level: int

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Settings:
        return cls(
            cors_origin=cls._cors_origin(env),
            force_https=cls._force_https(env),
            redis_url=cls._redis_url(env),
            log_level=cls._log_level(env),
        )

    @staticmethod
    def _cors_origin(env: Mapping[str, str]) -> str:
        origin = env.get("CORS_ORIGIN", "*").strip()
        if not origin:
            raise ValueError("CORS_ORIGIN is set but blank")
        return origin

    @staticmethod
    def _force_https(env: Mapping[str, str]) -> bool:
        raw = env.get("FORCE_HTTPS", "").strip().lower()
        if raw in _TRUE_TOKENS:
            return True
        if raw in _FALSE_TOKENS:
            return False
        raise ValueError(
            f"FORCE_HTTPS must be one of {sorted(_TRUE_TOKENS | _FALSE_TOKENS)},"
            f" got {raw!r}",
        )

    @staticmethod
    def _redis_url(env: Mapping[str, str]) -> str | None:
        url = env.get("REDISCLOUD_URL") or env.get("REDIS_URL") or None
        if url is not None and not url.startswith(_REDIS_SCHEMES):
            raise ValueError(
                f"REDIS_URL must start with one of {_REDIS_SCHEMES}, got {url!r}",
            )
        return url

    @staticmethod
    def _log_level(env: Mapping[str, str]) -> int:
        raw = env.get("LOG_LEVEL", "INFO").strip().upper()
        level = logging.getLevelNamesMapping().get(raw)
        if level is None:
            return logging.INFO
        return level


settings = Settings.from_env(os.environ)


LOG_FORMAT = "%(asctime)s %(levelname)-5s %(name)s [req=%(request_id)s] %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

_REQUEST_ID_RE = re.compile(r"\A[A-Za-z0-9._-]{1,64}\Z")


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, "request_id", None):
            return True
        record.request_id = g.get("request_id", "-") if has_request_context() else "-"
        return True


def configure_logging() -> None:
    level = Settings.from_env(os.environ).log_level

    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    formatter.converter = time.gmtime

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.addFilter(RequestIdFilter())

    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)

    raw = os.environ.get("LOG_LEVEL", "").strip()
    if raw and logging.getLevelNamesMapping().get(raw.upper()) is None:
        logging.getLogger(__name__).warning(
            "Unknown LOG_LEVEL %r - defaulting to INFO",
            raw,
        )


configure_logging()


app = Flask(
    __name__,
    template_folder=str(_webapp / "templates"),
    static_folder=str(_webapp / "static"),
)
app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=1,
    x_proto=1,
    x_host=0,
)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = (
    31536000
)
app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES
app.config["COMPRESS_BR_LEVEL"] = 9
app.config["COMPRESS_ZSTD_LEVEL"] = 12
app.config["COMPRESS_ALGORITHM"] = ["br", "zstd", "gzip", "deflate"]
app.config["COMPRESS_ALGORITHM_STREAMING"] = ["br", "zstd", "gzip", "deflate"]
Compress(app)
CORS(app, origins=[settings.cors_origin])


def _limiter_storage_uri() -> str:
    return Settings.from_env(os.environ).redis_url or "memory://"


_CLOUDFLARE_CIDRS = (
    "173.245.48.0/20",
    "103.21.244.0/22",
    "103.22.200.0/22",
    "103.31.4.0/22",
    "141.101.64.0/18",
    "108.162.192.0/18",
    "190.93.240.0/20",
    "188.114.96.0/20",
    "197.234.240.0/22",
    "198.41.128.0/17",
    "162.158.0.0/15",
    "104.16.0.0/13",
    "104.24.0.0/14",
    "172.64.0.0/13",
    "131.0.72.0/22",
    "2400:cb00::/32",
    "2606:4700::/32",
    "2803:f800::/32",
    "2405:b500::/32",
    "2405:8100::/32",
    "2a06:98c0::/29",
    "2c0f:f248::/32",
)
_CLOUDFLARE_NETWORKS = tuple(ipaddress.ip_network(cidr) for cidr in _CLOUDFLARE_CIDRS)


def _is_cloudflare_peer(address: str | None) -> bool:
    if not address:
        return False
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(parsed in network for network in _CLOUDFLARE_NETWORKS)


def _client_address() -> str:
    peer: str = get_remote_address()
    forwarded = request.headers.get("CF-Connecting-IP", "").strip()
    if not forwarded or not _is_cloudflare_peer(peer):
        return peer
    try:
        return str(ipaddress.ip_address(forwarded))
    except ValueError:
        return peer


limiter = Limiter(
    _client_address,
    app=app,
    default_limits=[RATE_LIMIT_DEFAULT],
    storage_uri=_limiter_storage_uri(),
    strategy="fixed-window",
    in_memory_fallback_enabled=True,
)


_log = logging.getLogger(__name__)

redis_client: redis.Redis[str] | None = None
_REDIS_RETRY_SECONDS = 30.0
_redis_next_attempt = 0.0


def _ensure_redis() -> None:
    global redis_client, _redis_next_attempt

    if redis_client is not None or not settings.redis_url:
        return

    now = time.monotonic()
    if now < _redis_next_attempt:
        return
    _redis_next_attempt = now + _REDIS_RETRY_SECONDS

    try:
        client: redis.Redis[str] = redis.Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_timeout=2,
        )
        client.ping()
    except Exception:
        _log.warning(
            "Redis unavailable - caching disabled, retrying in %ss",
            int(_REDIS_RETRY_SECONDS),
            exc_info=True,
        )
        return

    redis_client = client
    _log.info("Redis connection established")


def _drop_redis() -> None:
    global redis_client, _redis_next_attempt
    redis_client = None
    _redis_next_attempt = time.monotonic() + _REDIS_RETRY_SECONDS


_ensure_redis()

_cache_hits = 0
_cache_misses = 0

CATASTROPHIC_ERROR_MESSAGE = (
    "The solver failed unexpectedly. Please try again, and report this if it persists."
)

INTERNAL_ERROR_MESSAGE = "Internal server error."

_log.info("Relic Solver app started")


@app.before_request
def _redirect_to_https() -> WerkzeugResponse | None:
    if settings.force_https and not request.is_secure:
        return redirect(request.url.replace("http://", "https://", 1), code=308)
    return None


@app.before_request
def _start_timer() -> None:
    g.start_time = time.perf_counter()
    inbound = request.headers.get("X-Request-ID", "")
    g.request_id = inbound if _REQUEST_ID_RE.match(inbound) else secrets.token_hex(4)


@app.after_request
def _set_security_headers(response: Response) -> Response:
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "0"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), payment=()"
    )
    if request.is_secure:
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    script_src = "'self'"
    style_src = "'self'"
    for digest in g.get("csp_style_hashes", ()):
        style_src += f" {digest}"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        f"script-src {script_src}; "
        f"style-src {style_src}; "
        "img-src 'self'; "
        "connect-src 'self'; "
        "font-src 'self'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    )
    return response


@app.after_request
def _mark_static_immutable(response: Response) -> Response:
    if request.endpoint == "static" and response.cache_control.max_age:
        response.cache_control.immutable = True
    return response


@app.after_request
def _log_response_time(response: Response) -> Response:
    start: float | None = g.get("start_time", None)
    if start is not None:
        duration_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Response-Time"] = f"{duration_ms:.1f}ms"
    response.headers["X-Request-Id"] = g.get("request_id", "-")
    return response


_JSON_PATH_PREFIXES = ("/api/", "/solve")


def _wants_json() -> bool:
    if request.path.startswith(_JSON_PATH_PREFIXES):
        return True
    best: str | None = request.accept_mimetypes.best
    return best == "application/json"


@app.errorhandler(HTTPException)
def _handle_http_exception(
    exc: HTTPException,
) -> HTTPException | tuple[Response, int] | tuple[str, int]:
    if _wants_json():
        return jsonify(error=exc.description), exc.code or 500
    if exc.code == 404:
        return render_template("404.html"), 404
    return exc


@app.errorhandler(Exception)
def _handle_unexpected_exception(
    exc: Exception,
) -> HTTPException | tuple[Response, int]:
    _log.error("Unhandled exception serving %s", request.path, exc_info=exc)
    if not _wants_json():
        return InternalServerError()
    return jsonify(error=INTERNAL_ERROR_MESSAGE), 500


@app.context_processor
def inject_config() -> dict[str, object]:
    return {
        "cfg": {
            "MIN_RELIC_CAP": MIN_RELIC_CAP,
            "MAX_RELIC_CAP": MAX_RELIC_CAP,
            "DEFAULT_RELIC_CAP": DEFAULT_RELIC_CAP,
            "NUM_RELIC_TYPES": NUM_RELIC_TYPES,
            "COST_PER_REROLL": COST_PER_REROLL,
            "OBELISK_LEVEL_BANDS": OBELISK_LEVEL_BANDS,
            "OBELISK_D2_THRESHOLD": OBELISK_D2_THRESHOLD,
            "OBELISK_D3_THRESHOLD": OBELISK_D3_THRESHOLD,
            "OBELISK_D4_THRESHOLD": OBELISK_D4_THRESHOLD,
            "OBELISK_D5_THRESHOLD": OBELISK_D5_THRESHOLD,
        },
    }


_ASSET_HASH_LENGTH = 8


@functools.cache
def asset_version(filename: str) -> str:
    path = _webapp / "static" / filename
    if not path.is_file():
        _log.warning("No static asset to fingerprint: %s", filename)
        return solver_version
    return hashlib.sha256(path.read_bytes()).hexdigest()[:_ASSET_HASH_LENGTH]


_CSS_PARENT_URL_RE = re.compile(r"""url\(\s*(['"]?)\.\./""")


@functools.cache
def _read_static_text(filename: str, mtime_ns: int) -> str:
    return (_webapp / "static" / filename).read_text(encoding="utf-8")


def _csp_hash(text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return f"'sha256-{base64.b64encode(digest).decode('ascii')}'"


@app.context_processor
def inject_inline_asset() -> dict[str, object]:
    def inline_asset(filename: str) -> str:
        path = _webapp / "static" / filename
        try:
            text = _read_static_text(filename, path.stat().st_mtime_ns)
        except OSError:
            _log.warning("No static asset to inline: %s", filename)
            return ""
        static_root = url_for("static", filename="")
        rendered = _CSS_PARENT_URL_RE.sub(rf"url(\g<1>{static_root}", text)
        hashes = g.get("csp_style_hashes")
        if hashes is None:
            hashes = g.csp_style_hashes = []
        digest = _csp_hash(rendered)
        if digest not in hashes:
            hashes.append(digest)
        return rendered

    return {"inline_asset": inline_asset}


@app.context_processor
def inject_asset_url() -> dict[str, object]:
    def asset_url(filename: str) -> str:
        return f"{url_for('static', filename=filename)}?v={asset_version(filename)}"

    return {"asset_url": asset_url}


@app.route("/")
def index() -> Response:
    resp = make_response(render_template("index.html"))
    resp.headers["Cache-Control"] = "public, max-age=300"
    return resp


@app.route("/privacy")
def privacy() -> Response:
    resp = make_response(render_template("privacy.html"))
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


def _redis_state() -> str:
    if not settings.redis_url:
        return "absent"
    if redis_client is None:
        return "down"
    try:
        redis_client.ping()
    except Exception:
        _log.warning("Redis ping failed in health check", exc_info=True)
        return "down"
    return "up"


@app.route("/api/health")
@limiter.exempt
def health() -> Response:
    entries: int | None = None
    total_hits: int | None = None
    total_misses: int | None = None

    if redis_client is not None:
        try:
            pipe = redis_client.pipeline()
            pipe.dbsize()
            pipe.get("stats:cache_hits")
            pipe.get("stats:cache_misses")
            db_size, raw_hits, raw_misses = pipe.execute()
            entries = db_size
            total_hits = int(raw_hits) if raw_hits else 0
            total_misses = int(raw_misses) if raw_misses else 0
        except Exception:
            _log.warning("Redis stats query failed in health check", exc_info=True)

    if total_hits is not None and total_misses is not None:
        redis_total = total_hits + total_misses
        hit_rate = round(total_hits / max(redis_total, 1), 3)
    else:
        instance_total = _cache_hits + _cache_misses
        hit_rate = round(_cache_hits / max(instance_total, 1), 3)

    redis_state = _redis_state()

    return jsonify(
        {
            "status": "degraded" if redis_state == "down" else "ok",
            "solver_version": solver_version,
            "dependencies": {"redis": redis_state},
            "cache": {
                "backend": "redis" if redis_client else "none",
                "entries": entries,
                "hit_rate": hit_rate,
                "total_hits": total_hits,
                "total_misses": total_misses,
                "instance_hits": _cache_hits,
                "instance_misses": _cache_misses,
            },
        },
    )


_ROOT_FILE_MAX_AGE = 3600


@app.route("/robots.txt")
@app.route("/favicon.ico")
@app.route("/manifest.json")
def static_from_root() -> Response:
    return send_from_directory(
        app.static_folder,
        request.path[1:],
        max_age=_ROOT_FILE_MAX_AGE,
    )


def _template_lastmod(name: str) -> str:
    template = _webapp / "templates" / name
    if not template.is_file():
        return datetime.now(UTC).strftime("%Y-%m-%d")
    stamp = datetime.fromtimestamp(template.stat().st_mtime, UTC)
    return stamp.strftime("%Y-%m-%d")


@app.route("/sitemap.xml")
def sitemap() -> Response:
    resp = make_response(
        render_template(
            "sitemap.xml",
            lastmod=_template_lastmod("index.html"),
            privacy_lastmod=_template_lastmod("privacy.html"),
        ),
    )
    resp.headers["Content-Type"] = "application/xml; charset=utf-8"
    resp.headers["Cache-Control"] = f"public, max-age={_ROOT_FILE_MAX_AGE}"
    return resp


@app.route("/.well-known/security.txt")
@app.route("/.well-known/pgp-key.txt")
@limiter.exempt
def well_known_security() -> Response:
    resp = send_from_directory(
        app.static_folder,
        request.path[1:],
        max_age=_ROOT_FILE_MAX_AGE,
    )
    resp.headers["Content-Type"] = "text/plain; charset=utf-8"
    return resp


@app.route("/security.txt")
@limiter.exempt
def security_txt_legacy() -> WerkzeugResponse:
    return redirect("/.well-known/security.txt", code=301)


@app.route("/.well-known/<path:_path>")
@limiter.exempt
def well_known(_path: str) -> Response:
    return Response(status=204)


def _cache_key(
    chests: int,
    divines: int,
    cap: int,
    obelisk: int,
    targets: tuple[int, ...],
) -> str:
    target_csv = ",".join(str(t) for t in targets)
    return f"solve:{chests}:{divines}:{cap}:{obelisk}:{target_csv}"


def _ndjson_line(obj: dict[str, object]) -> str:
    return json.dumps(obj, separators=(",", ":")) + "\n"


def _make_etag(cache_key: str) -> str:
    digest = hashlib.sha256(cache_key.encode()).hexdigest()[:16]
    return f'"{digest}"'


def _incr_stat(name: str) -> None:
    if redis_client is not None:
        try:
            redis_client.incr(f"stats:{name}")
        except Exception:
            _log.debug("Redis INCR failed for stats:%s", name)


def _validate_solve_input(data: object) -> dict[str, object] | tuple[Response, int]:
    if not isinstance(data, dict):
        return jsonify(error="Request body must be a JSON object"), 400

    required = (
        "total_relic_chests",
        "divine_chests",
        "relic_cap",
        "obelisk_level",
        "targets",
    )
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify(error=f"Missing fields: {', '.join(missing)}"), 400

    errors: list[str] = []

    raw_chests = data["total_relic_chests"]
    raw_divines = data["divine_chests"]
    raw_cap = data["relic_cap"]
    raw_obelisk = data["obelisk_level"]
    raw_targets = data["targets"]

    if not isinstance(raw_chests, int | float) or raw_chests != int(raw_chests):
        errors.append("total_relic_chests must be an integer")
    elif int(raw_chests) < 0:
        errors.append("total_relic_chests must be non-negative")

    if not isinstance(raw_divines, int | float) or raw_divines != int(raw_divines):
        errors.append("divine_chests must be an integer")
    elif int(raw_divines) < 0:
        errors.append("divine_chests must be non-negative")

    if not isinstance(raw_cap, int | float) or raw_cap != int(raw_cap):
        errors.append("relic_cap must be an integer")
    elif not (MIN_RELIC_CAP <= int(raw_cap) <= MAX_RELIC_CAP):
        errors.append(f"relic_cap must be between {MIN_RELIC_CAP} and {MAX_RELIC_CAP}")

    if not isinstance(raw_obelisk, int | float) or raw_obelisk != int(raw_obelisk):
        errors.append("obelisk_level must be an integer")
    elif not (MIN_OBELISK_LEVEL <= int(raw_obelisk) <= MAX_OBELISK_LEVEL):
        errors.append(
            f"obelisk_level must be between {MIN_OBELISK_LEVEL}"
            f" and {MAX_OBELISK_LEVEL}",
        )

    if not isinstance(raw_targets, list):
        errors.append("targets must be an array")
    elif len(raw_targets) != NUM_RELIC_TYPES:
        errors.append(f"targets must have exactly {NUM_RELIC_TYPES} values")
    else:
        for i, t in enumerate(raw_targets):
            if not isinstance(t, int | float) or t != int(t):
                errors.append(f"targets[{i}] must be an integer")
            elif int(t) < 0:
                errors.append(f"targets[{i}] must be non-negative")
            elif i > 0 and int(t) > MAX_RELIC_CAP:
                errors.append(
                    f"targets[{i}] (D{i + 1}) must not exceed {MAX_RELIC_CAP}",
                )

    if errors:
        return jsonify(error="; ".join(errors)), 400

    return {
        "total_relic_chests": int(raw_chests),
        "divine_chests": int(raw_divines),
        "relic_cap": int(raw_cap),
        "obelisk_level": int(raw_obelisk),
        "targets": tuple(int(t) for t in raw_targets),
    }


@app.route("/solve", methods=["POST"])
@limiter.limit(RATE_LIMIT_SOLVE)
def run_solver() -> Response | tuple[Response, int]:
    data = request.get_json(force=True)
    validated = _validate_solve_input(data)

    if isinstance(validated, tuple):
        _log.warning("Validation error: %s", validated[0].get_json())
        return validated

    total_relic_chests: int = validated["total_relic_chests"]  # type: ignore[assignment]
    divine_chests: int = validated["divine_chests"]  # type: ignore[assignment]
    relic_cap: int = validated["relic_cap"]  # type: ignore[assignment]
    obelisk_level: int = validated["obelisk_level"]  # type: ignore[assignment]
    targets: tuple[int, ...] = validated["targets"]  # type: ignore[assignment]

    log_context = {"request_id": g.get("request_id", "-")}

    global _cache_hits, _cache_misses  # noqa: PLW0603
    _ensure_redis()

    normalized = (targets[0], *(min(t, relic_cap) for t in targets[1:]))
    key = _cache_key(
        total_relic_chests,
        divine_chests,
        relic_cap,
        obelisk_level,
        normalized,
    )

    if redis_client is not None:
        try:
            cached = redis_client.get(key)
        except Exception:
            _log.warning(
                "Redis GET failed for key %s - dropping the client",
                key,
                exc_info=True,
            )
            _drop_redis()
            cached = None
        if cached is not None:
            _cache_hits += 1
            _incr_stat("cache_hits")

            etag = _make_etag(key)
            if request.headers.get("If-None-Match") == etag:
                return Response(status=304, headers={"ETag": etag})

            hit = json.loads(cached)
            hit["type"] = "result"
            hit["cached"] = True
            resp = Response(
                _ndjson_line(hit),
                mimetype="application/x-ndjson",
            )
            resp.headers["ETag"] = etag
            return resp
        _cache_misses += 1
        _incr_stat("cache_misses")

    q: queue.Queue[dict[str, object] | None] = queue.Queue()

    def _progress(step: int, total: int) -> None:
        pct = int(step / total * 100) if total else 0
        q.put({"type": "progress", "percent": pct})

    def _worker() -> None:
        t0 = time.perf_counter()
        try:
            prob = solve(
                total_relic_chests,
                divine_chests,
                targets,
                relic_cap=relic_cap,
                obelisk_level=obelisk_level,
                max_seconds=SOLVE_MAX_SECONDS,
                progress_callback=_progress,
            )
            duration_ms = (time.perf_counter() - t0) * 1000
            rerolls = expected_rerolls(prob)
            gems = expected_gems(prob)

            if prob == 0:
                _log.warning(
                    "Impossible solve (0%%): duration_ms=%s",
                    round(duration_ms, 1),
                    extra=log_context,
                )
            else:
                _log.info(
                    "Solve complete: probability=%s rerolls=%s gems=%s duration_ms=%s",
                    prob,
                    rerolls if not math.isinf(rerolls) else None,
                    gems if not math.isinf(gems) else None,
                    round(duration_ms, 1),
                    extra=log_context,
                )

            result_data = {
                "probability": prob,
                "expected_rerolls": rerolls if not math.isinf(rerolls) else None,
                "expected_gems": gems if not math.isinf(gems) else None,
            }
            q.put(
                {
                    "type": "result",
                    **result_data,
                    "solve_time_ms": round(duration_ms, 1),
                },
            )

            if redis_client is not None:
                try:
                    redis_client.set(key, json.dumps(result_data))
                except Exception:
                    _log.warning(
                        "Redis SET failed for key %s - dropping the client",
                        key,
                        exc_info=True,
                        extra=log_context,
                    )
                    _drop_redis()

            if redis_client is not None:
                try:
                    entry = json.dumps(
                        {
                            "ts": int(time.time()),
                            "chests": total_relic_chests,
                            "divines": divine_chests,
                            "cap": relic_cap,
                            "ob": obelisk_level,
                            "targets": list(targets),
                            "prob": round(prob, 8),
                            "ms": round(duration_ms, 1),
                        },
                    )
                    pipe = redis_client.pipeline()
                    pipe.lpush("analytics:solves", entry)
                    pipe.ltrim("analytics:solves", 0, 49999)
                    pipe.execute()
                except Exception:
                    _log.debug("Redis usage write failed")

        except (ValueError, TimeoutError) as exc:
            duration_ms = (time.perf_counter() - t0) * 1000
            error_type = "timeout" if isinstance(exc, TimeoutError) else "value_error"
            _log.error(
                "Solve failed: %s - %s (duration_ms=%s)",
                error_type,
                exc,
                round(duration_ms, 1),
                extra=log_context,
            )
            q.put({"type": "error", "error": str(exc)})
        except Exception:
            duration_ms = (time.perf_counter() - t0) * 1000
            _log.error(
                "Solve crashed unexpectedly (duration_ms=%s)",
                round(duration_ms, 1),
                exc_info=True,
                extra=log_context,
            )
            q.put({"type": "error", "error": CATASTROPHIC_ERROR_MESSAGE})
        finally:
            q.put(None)

    def _generate() -> Generator[str]:
        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        while True:
            try:
                msg = q.get(timeout=20)
            except queue.Empty:
                yield _ndjson_line({"type": "progress", "percent": -1})
                continue
            if msg is None:
                break
            yield _ndjson_line(msg)

    return Response(
        stream_with_context(_generate()),
        mimetype="application/x-ndjson",
    )


if __name__ == "__main__":
    app.run()
