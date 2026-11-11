from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

API = "https://api.cloudflare.com/client/v4/ips"


def fetch_published() -> tuple[set[str], str]:
    request = urllib.request.Request(  # noqa: S310 - fixed https URL
        API,
        headers={"User-Agent": "relic-solver-ip-check", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=25) as response:  # noqa: S310
        payload = json.load(response)

    if not payload.get("success"):
        raise RuntimeError(f"Cloudflare reported failure: {payload.get('errors')}")

    result = payload["result"]
    return set(result["ipv4_cidrs"]) | set(result["ipv6_cidrs"]), result.get("etag", "")


def main() -> int:
    from app import _CLOUDFLARE_CIDRS  # noqa: PLC0415 - after the sys.path line above

    try:
        published, etag = fetch_published()
    except (urllib.error.URLError, TimeoutError, RuntimeError, KeyError) as exc:
        print(f"could not read {API}: {exc}", file=sys.stderr)
        return 2

    baked = set(_CLOUDFLARE_CIDRS)
    missing = sorted(published - baked)
    stale = sorted(baked - published)

    if not missing and not stale:
        print(
            f"app.py matches the published list ({len(published)} ranges, etag {etag})",
        )
        return 0

    print(f"app.py has drifted from the published list (etag {etag})")
    for cidr in missing:
        print(f"  + {cidr}  published, not in app.py")
    for cidr in stale:
        print(f"  - {cidr}  in app.py, no longer published")
    print("\nUpdate _CLOUDFLARE_CIDRS in app.py, and the etag in the comment above it.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
