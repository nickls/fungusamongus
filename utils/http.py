"""Shared HTTP helpers."""

import requests


def fetch_json(url: str, params: dict | None = None, timeout: int = 30) -> dict | None:
    try:
        r = requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  [warn] {url[:60]}... -- {e}")
        return None
