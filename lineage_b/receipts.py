"""Append-only, hash-chained prediction receipt store with a logical clock
(B0 §9, gate 8)."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Tuple


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


class ReceiptError(RuntimeError):
    pass


class ReceiptStore:
    GENESIS = "0" * 64

    def __init__(self):
        self._chain = []                       # (clock, key, hash, prev, payload_json)
        self._index: Dict[Tuple, int] = {}
        self._clock = 0

    def tick(self) -> int:
        self._clock += 1
        return self._clock

    def commit(self, key: Tuple, payload: Dict[str, Any]) -> str:
        if key in self._index:
            raise ReceiptError(f"receipt {key} already committed (no rewriting)")
        prev = self._chain[-1][2] if self._chain else self.GENESIS
        body = canonical(payload)
        h = hashlib.sha256((prev + canonical(list(key)) + body).encode()).hexdigest()
        clock = self.tick()
        self._index[key] = len(self._chain)
        self._chain.append((clock, key, h, prev, body))
        return h

    def has(self, key) -> bool:
        return key in self._index

    def hash_of(self, key):
        i = self._index.get(key)
        return None if i is None else self._chain[i][2]

    def clock_of(self, key):
        return self._chain[self._index[key]][0]

    def payload(self, key) -> Dict[str, Any]:
        return json.loads(self._chain[self._index[key]][4])

    def verify(self) -> bool:
        prev = self.GENESIS
        for clock, key, h, p, body in self._chain:
            if p != prev or hashlib.sha256((p + canonical(list(key)) + body).encode()).hexdigest() != h:
                return False
            prev = h
        return True

    def __len__(self):
        return len(self._chain)
