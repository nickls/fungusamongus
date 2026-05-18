"""Shared HTTP helpers — retry with backoff, global rate limit, polite UA."""
from __future__ import annotations

import random
import threading
import time
from typing import Any

import requests

from config import (HTTP_CONNECT_TIMEOUT, HTTP_RATE_LIMIT_RPS, HTTP_READ_TIMEOUT,
                    HTTP_RETRIES, HTTP_USER_AGENT)


# Global rate limiter shared across all worker threads. Most calls go to
# Open-Meteo, where bursts from our 6 worker threads on a shared GH Actions
# IP have historically triggered 429s. Capping global RPS keeps us under
# Open-Meteo's per-minute fair-use limit even when neighbors on the same
# runner IP are also calling.
_rate_lock = threading.Lock()
_min_interval = 1.0 / HTTP_RATE_LIMIT_RPS
_last_request_time = 0.0


def _rate_limit() -> None:
    global _last_request_time
    with _rate_lock:
        now = time.monotonic()
        wait = _min_interval - (now - _last_request_time)
        if wait > 0:
            time.sleep(wait)
        _last_request_time = time.monotonic()


def fetch_json(
    url: str,
    params: dict | None = None,
    *,
    timeout: int | None = None,  # legacy alias for read_timeout
    connect_timeout: int = HTTP_CONNECT_TIMEOUT,
    read_timeout: int = HTTP_READ_TIMEOUT,
    retries: int = HTTP_RETRIES,
) -> dict | None:
    """GET a URL and parse JSON, with backoff for transient failures.

    Retryable: read/connect timeouts, 5xx, 429. Terminal: other 4xx, parse error.
    Backoff for 429 honors Retry-After header when present, else 60s * 2^attempt.
    Backoff for timeout/5xx is 2s * 2^attempt with jitter.

    Returns None only after exhausting all retries — callers should treat None
    as "data unavailable" and either fall back to stale cache or skip the site.
    """
    if timeout is not None:
        read_timeout = timeout

    headers = {"User-Agent": HTTP_USER_AGENT, "Accept": "application/json"}
    last_err: Any = None

    for attempt in range(retries + 1):
        _rate_limit()
        try:
            r = requests.get(
                url, params=params, headers=headers,
                timeout=(connect_timeout, read_timeout),
            )
        except (requests.Timeout, requests.ConnectionError) as e:
            last_err = e
            if attempt >= retries:
                break
            time.sleep(2 * (2 ** attempt) + random.uniform(0, 1))
            continue
        except Exception as e:
            # Bad URL, DNS failure, etc. — terminal.
            last_err = e
            break

        if r.status_code == 429:
            last_err = "429 Too Many Requests"
            if attempt >= retries:
                break
            retry_after = r.headers.get("Retry-After")
            try:
                base_wait = float(retry_after) if retry_after else 60 * (2 ** attempt)
            except ValueError:
                base_wait = 60 * (2 ** attempt)
            time.sleep(base_wait + random.uniform(0, 2))
            continue

        if 500 <= r.status_code < 600:
            last_err = f"{r.status_code} server error"
            if attempt >= retries:
                break
            time.sleep(2 * (2 ** attempt) + random.uniform(0, 1))
            continue

        try:
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            break

    print(f"  [warn] {url[:60]}... -- {last_err}")
    return None
