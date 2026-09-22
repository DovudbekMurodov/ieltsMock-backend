"""Helpers for materialised publish payloads."""

import hashlib
import json


def canonical_json(payload) -> str:
    """Stable JSON text for hashing.

    Sorted keys and fixed separators so an unchanged payload always hashes to
    the same ETag, regardless of dict ordering.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def payload_etag(payload) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
