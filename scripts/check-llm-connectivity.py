"""LLM provider connectivity check.

Verifies that the active model profile (or a named profile) can reach its
upstream /v1/models endpoint with the configured API key. Never prints
the key value; only its source channel and a fingerprint (length plus
first and last two characters).

Exit codes:
- 0: HTTP 200 with a recognized models-list response.
- 1: profile not found, or no API key resolvable from the configured env vars.
- 2: HTTP error (4xx / 5xx). Status code is printed; response body is NOT.
- 3: network or timeout error.
- 4: response was not a recognized models-list shape.

The script writes one model_calls row when the EYEX database is available
so the connectivity check is part of the durable observability ledger.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _redact(key):
    if not key:
        return {"present": False, "length": 0, "fingerprint": None}
    cleaned = key.strip()
    if len(cleaned) <= 6:
        return {"present": True, "length": len(cleaned), "fingerprint": "***"}
    return {
        "present": True,
        "length": len(cleaned),
        "fingerprint": cleaned[:2] + "..." + cleaned[-2:],
    }


def _resolve_key(profile, settings):
    try:
        from app.services.model_auth import api_keys_for_profile
    except Exception:
        api_keys_for_profile = None
    if api_keys_for_profile is not None:
        try:
            keys = api_keys_for_profile(profile)
        except Exception:
            keys = []
        if keys:
            return keys[0], "model_auth.api_keys_for_profile"
    env_var = profile.api_key_env
    candidates = [env_var] if env_var else []
    candidates.extend(profile.auth_env_vars or [])
    for var in candidates:
        if not var:
            continue
        value = os.environ.get(var)
        if value:
            return value, "env:" + var
    return None, None


def _classify(body):
    if not isinstance(body, dict):
        return False, 0, None
    for key in ("data", "models"):
        items = body.get(key)
        if isinstance(items, list):
            first = None
            for item in items:
                if isinstance(item, dict):
                    first = item.get("id") or item.get("model") or item.get("name")
                    if first:
                        break
                elif isinstance(item, str):
                    first = item
                    break
            return True, len(items), first
    return False, 0, None


def _record(profile_id, base_url, status_code, duration_ms, success, model_count, error_label):
    try:
        from app.core.database import ModelCallRecord, SessionLocal, init_db
    except Exception:
        return
    try:
        init_db()
    except Exception:
        return
    db = SessionLocal()
    try:
        record = ModelCallRecord(
            call_id="connectivity-" + uuid.uuid4().hex[:12],
            run_id="connectivity-" + uuid.uuid4().hex[:12],
            case_id="__connectivity_check__",
            stage="connectivity_check",
            provider=(profile_id.split("_")[0] if profile_id else "unknown"),
            model=profile_id + " via " + base_url,
            mode="models_list",
            field_keys_json="[]",
            input_tokens=0,
            cached_input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            duration_ms=duration_ms,
            status=("completed" if success else "failed"),
            error_code=(None if success else ("HTTP_" + str(status_code) if status_code else error_label)),
            error_message=error_label,
            fallback_attempts=0,
            fallback_failures=0,
            fallback_errors_json="[]",
            llm_cache_status=None,
            llm_cache_key=None,
        )
        db.add(record)
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


def _candidates(base):
    urls = [base + "/v1/models", base + "/models"]
    if base.endswith("/v1"):
        urls.append(base[:-3] + "/v1/models")
        urls.append(base[:-3] + "/models")
    out = []
    seen = set()
    for url in urls:
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def main():
    parser = argparse.ArgumentParser(description="EYEX LLM provider connectivity check.")
    parser.add_argument("--profile-id", default="", help="Model profile id (default: active profile in settings).")
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()

    print("== EYEX LLM connectivity check ==", flush=True)

    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=False)
    except Exception:
        pass

    try:
        from app.core.config_loader import load_model_profile
        from app.core.settings import settings
    except Exception as exc:
        print("FAIL: cannot import EYEX backend modules: " + str(exc), flush=True)
        return 1

    profile_id = args.profile_id or settings.model_profile
    print("profile_id: " + profile_id, flush=True)
    try:
        profile = load_model_profile(profile_id)
    except Exception as exc:
        print("FAIL: cannot load model profile: " + str(exc), flush=True)
        return 1

    base_url = (profile.base_url or "").rstrip("/")
    if not base_url:
        print("FAIL: profile has no base_url declared.", flush=True)
        return 1

    print("provider_id: " + (profile.provider_id or "(unset)"), flush=True)
    print("api: " + (profile.api or "unknown"), flush=True)
    print("base_url: " + base_url, flush=True)
    print("model: " + profile.model, flush=True)

    key, source = _resolve_key(profile, settings)
    meta = _redact(key)
    print("api_key_present: " + str(meta["present"]), flush=True)
    print("api_key_length: " + str(meta["length"]), flush=True)
    print("api_key_fingerprint: " + str(meta["fingerprint"]), flush=True)
    print("api_key_source: " + (source or "none"), flush=True)
    if not key:
        print("FAIL: no API key resolved.", flush=True)
        return 1

    try:
        import httpx
    except Exception as exc:
        print("FAIL: httpx unavailable: " + str(exc), flush=True)
        return 1

    last_status = 0
    last_error = None
    started = time.perf_counter()

    for url in _candidates(base_url):
        print("GET: " + url, flush=True)
        headers = {"Authorization": "Bearer " + key}
        try:
            with httpx.Client(timeout=args.timeout) as client:
                response = client.get(url, headers=headers)
                last_status = response.status_code
                if response.status_code in (404, 405):
                    print("  status: " + str(response.status_code) + " (trying next path)", flush=True)
                    continue
                if response.status_code >= 400:
                    duration_ms = int((time.perf_counter() - started) * 1000)
                    print("  status: " + str(response.status_code), flush=True)
                    print("FAIL: provider returned error. Body NOT printed.", flush=True)
                    _record(profile_id, base_url, response.status_code, duration_ms, False, 0, "HTTP_" + str(response.status_code))
                    return 2
                try:
                    body = response.json()
                except json.JSONDecodeError as exc:
                    duration_ms = int((time.perf_counter() - started) * 1000)
                    print("FAIL: response was not JSON.", flush=True)
                    _record(profile_id, base_url, response.status_code, duration_ms, False, 0, "json_decode")
                    return 4
                ok, count, first = _classify(body)
                duration_ms = int((time.perf_counter() - started) * 1000)
                if not ok:
                    print("FAIL: response not a recognized models list.", flush=True)
                    _record(profile_id, base_url, response.status_code, duration_ms, False, 0, "unexpected_shape")
                    return 4
                print("  status: " + str(response.status_code), flush=True)
                print("  model_count: " + str(count), flush=True)
                print("  first_model: " + (first or "(unknown)"), flush=True)
                print("  duration_ms: " + str(duration_ms), flush=True)
                print("OK: provider reachable, /v1/models returned a recognized list.", flush=True)
                _record(profile_id, base_url, response.status_code, duration_ms, True, count, None)
                return 0
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            last_error = type(exc).__name__
            print("  network error: " + last_error + " (trying next path)", flush=True)
            continue
        except Exception as exc:
            last_error = type(exc).__name__
            print("  unexpected error: " + last_error, flush=True)
            break

    duration_ms = int((time.perf_counter() - started) * 1000)
    print("FAIL: no /v1/models URL succeeded. last_status=" + str(last_status) + " last_error=" + str(last_error), flush=True)
    _record(profile_id, base_url, last_status or 0, duration_ms, False, 0, last_error or "no_url_succeeded")
    return 3 if last_error else 2


if __name__ == "__main__":
    raise SystemExit(main())
