"""Local JSON file cache with TTL."""

import hashlib
import json
import time
from pathlib import Path

from config import CACHE_DIR


def cache_key(prefix: str, **kwargs) -> str:
    raw = f"{prefix}:{json.dumps(kwargs, sort_keys=True)}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def cache_get(key: str, ttl_hours: float) -> dict | None:
    path = CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    age_hours = (time.time() - path.stat().st_mtime) / 3600
    if age_hours > ttl_hours:
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def cache_set(key: str, data):
    CACHE_DIR.mkdir(exist_ok=True)
    (CACHE_DIR / f"{key}.json").write_text(json.dumps(data))
