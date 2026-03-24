"""
MorphSAT Receipt Utilities
===========================

Lightweight receipt serialization for audit trails.

Every MorphSAT gate produces a receipt via :meth:`MorphSATGate.to_receipt`.
This module provides helpers for wrapping receipts with timestamps and
computing content hashes.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, Optional


def wrap_receipt(
    tag: str,
    payload: Dict[str, Any],
    *,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Wrap a payload dict into a timestamped receipt with a content hash.

    Args:
        tag: Short identifier for the receipt (e.g. ``"fsa-run-01"``).
        payload: The data to include.
        extra: Optional additional metadata merged at the top level.

    Returns:
        A dict with ``tag``, ``timestamp``, ``payload``, and ``sha256``
        of the JSON-serialized payload.
    """
    payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload_json.encode()).hexdigest()

    receipt: Dict[str, Any] = {
        "tag": tag,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "sha256": digest,
        "payload": payload,
    }

    if extra:
        receipt.update(extra)

    return receipt
