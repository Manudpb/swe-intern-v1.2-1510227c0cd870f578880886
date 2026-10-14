#!/usr/bin/env python3
"""Claude readiness check: the equivalent of `configure_access.py application-check` for this app.

The packet's check sends a Chat Completions request on the ACCESS.json *application* route. This app
calls Claude through the Anthropic Messages API on the funded Portkey gateway (the coordinator
approved any provider), so this check exercises that path:

  POST <gateway root>/v1/messages with x-portkey-api-key and x-portkey-provider,
  model from CLAUDE_MODEL_ROUTE (default: models.claude in ACCESS.json)

It sends ONE small paid request (45-second timeout, no retries, TLS verification on), checks for a
usable text reply, and prints neither credentials nor the model's reply. It does not check Docker
environment forwarding, images or tools. Standard library only.
Usage (from starter-kit/):  python scripts/check_claude_access.py --env-file .env
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

PACKET_ROOT = Path(__file__).resolve().parents[2]
ANTHROPIC_VERSION = "2023-06-01"
FIELDS = {"PORTKEY_API_KEY", "PORTKEY_BASE_URL", "CLAUDE_MODEL_ROUTE"}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def read_settings(env_file, environment):
    """Literal single-line values from .env; the environment wins (same rules as configure_access.py)."""
    values = {}
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            name, separator, value = line.strip().partition("=")
            name = name.strip()
            if not separator or name not in FIELDS:
                continue
            value = value.strip()
            if value.startswith(('"', "'")):
                if len(value) < 2 or value[-1] != value[0]:
                    raise ValueError("Use single-line matched quotes in .env")
                value = value[1:-1]
            if "$" in value or "`" in value:
                raise ValueError("Use literal settings in .env; expansion is not supported")
            values[name] = value
    values.update({name: environment[name] for name in FIELDS if name in environment})
    return values


def portkey_target(profile, settings):
    """Validate the funded profile like the packet check, then build the Messages request target."""
    if profile.get("mode") != "live":
        raise ValueError("This packet has no funded access; request your funded packet")
    expiry = datetime.fromisoformat(profile["expires_at"].replace("Z", "+00:00"))
    if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
        raise ValueError("The access profile has expired or lacks a timezone; contact support")
    gateway = profile["gateway_base_url"].rstrip("/")
    parsed = urllib.parse.urlsplit(gateway)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or not parsed.path.endswith("/v1")):
        raise ValueError("Invalid HTTPS gateway in access profile; contact support")
    if settings.get("PORTKEY_BASE_URL", gateway).rstrip("/") != gateway:
        raise ValueError("PORTKEY_BASE_URL must match gateway_base_url in ACCESS.json")
    key = settings.get("PORTKEY_API_KEY", "")
    if not key or any(c.isspace() for c in key):
        raise ValueError("PORTKEY_API_KEY is missing or invalid in starter-kit/.env; contact the coordinator")
    route = settings.get("CLAUDE_MODEL_ROUTE") or profile["models"].get("claude", "")
    provider, _, model = route.partition("/")
    if not provider.startswith("@anthropic") or not model or any(c.isspace() for c in route):
        raise ValueError("CLAUDE_MODEL_ROUTE must be an Anthropic route like @anthropic---x/claude-opus-5")
    # The Anthropic SDK path: gateway ROOT (no /v1) + /v1/messages, unprefixed model, provider header.
    url = gateway.removesuffix("/v1") + "/v1/messages"
    headers = {"x-api-key": key, "x-portkey-api-key": key, "x-portkey-provider": provider}
    return url, headers, model


def check_claude(profile, settings, opener=None):
    url, headers, model = portkey_target(profile, settings)

    # max_tokens leaves room for a little adaptive thinking; the reply itself is one word.
    body = json.dumps({"model": model, "max_tokens": 256,
                       "messages": [{"role": "user", "content": "Reply with OK."}]}).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST", headers={
        **headers, "anthropic-version": ANTHROPIC_VERSION,
        "Content-Type": "application/json", "User-Agent": "claim-triage-readiness/1.0"})
    opener = opener or urllib.request.build_opener(NoRedirect())
    started = perf_counter()
    try:
        with opener.open(request, timeout=45) as response:
            payload = json.loads(response.read(65536))
        if payload.get("stop_reason") == "refusal":
            raise ValueError("refusal")
        text = "".join(b.get("text", "") for b in payload["content"] if b.get("type") == "text")
        if not text.strip():
            raise ValueError("empty reply")
    except urllib.error.HTTPError as exc:
        status = exc.code
        exc.close()
        if status in (401, 403):
            message = "Authentication or route access denied; check the key and the Claude route"
        elif status == 404:
            message = "Model or route not found; check CLAUDE_MODEL_ROUTE"
        elif status == 429:
            message = "Rate limit or allowance exhausted; pause and contact support; no automatic retry"
        elif status in (500, 502, 503, 529):
            message = "Provider unavailable or overloaded; try again later"
        else:
            message = "Request rejected; share the HTTP status (not the key) with support"
        raise ValueError(f"{message} (HTTP {status})") from None
    except (urllib.error.URLError, OSError):
        raise ValueError("Cannot reach the gateway (network, TLS or timeout); TLS verification remains enabled") from None
    except (ValueError, KeyError, IndexError, TypeError):
        raise ValueError("No usable reply (empty, refused or malformed); contact support") from None
    return {
        "status": "ok", "model": payload.get("model", model),
        "elapsed_ms": round((perf_counter() - started) * 1000),
        "check": "One small Claude Messages request through the Portkey gateway; "
                 "Docker forwarding, vision and tools still need application tests",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--profile", type=Path, default=PACKET_ROOT / "ACCESS.json")
    args = parser.parse_args()
    try:
        profile = json.loads(args.profile.read_text(encoding="utf-8-sig"))
        result = check_claude(profile, read_settings(args.env_file, os.environ))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"Claude readiness check FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
