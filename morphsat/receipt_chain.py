"""
MorphSAT Receipt Chain — Layer 1: Immutable Provenance Spine
=============================================================

Append-only hash chain of receipt blocks. Never rewrites, never forgets.

Architecture:
    Receipt → canonical hash → block accumulator → close_block() →
    block header (previous_hash, receipt_hashes, block_hash) →
    chain grows by one block

The chain is the fossil record. Layer 2 (receipt graph) builds living
memory on top of it. This layer only does tamper-evident storage.

Design decisions:
    - Linear chain, not Merkle tree (sufficient at current scale;
      upgrade to Merkle when privacy-preserving audit is needed)
    - Canonical JSON: json.dumps(sort_keys=True, separators=(",",":"))
      Same convention as receipt.py:wrap_receipt(). NOT full RFC 8785
      JCS — documented constraint, acceptable for single-box use.
    - Block numbers are sequential (0, 1, 2, ...)
    - Genesis block has previous_hash = "0" * 64
    - Chain state persists to a single JSON file
    - verify_chain() walks the full chain and checks every link
    - verify_receipt_in_block() proves a receipt is in a specific block
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Canonical hashing — same convention as receipt.py
# ---------------------------------------------------------------------------

def canonical_json(obj: Any) -> str:
    """Deterministic JSON serialization for hashing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def canonical_hash(obj: Any) -> str:
    """SHA256 of canonical JSON representation."""
    return hashlib.sha256(canonical_json(obj).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Block
# ---------------------------------------------------------------------------

GENESIS_HASH = "0" * 64


@dataclass
class ReceiptBlock:
    """One block in the receipt chain.

    A block contains N receipts, a link to the previous block,
    and a hash computed over (previous_hash + all receipt hashes).
    """
    block_number: int
    previous_hash: str
    receipt_hashes: List[str]
    timestamp: str
    block_hash: str = ""

    def compute_hash(self) -> str:
        """Compute block hash from previous_hash + receipt hashes."""
        preimage = self.previous_hash + "|".join(self.receipt_hashes)
        return hashlib.sha256(preimage.encode()).hexdigest()

    def seal(self) -> None:
        """Compute and store the block hash. Idempotent."""
        self.block_hash = self.compute_hash()

    def verify(self) -> bool:
        """Check that stored block_hash matches recomputed hash."""
        return self.block_hash == self.compute_hash()

    def contains_receipt(self, receipt_hash: str) -> bool:
        """Check if a receipt hash is in this block."""
        return receipt_hash in self.receipt_hashes

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ReceiptBlock:
        return cls(**d)


# ---------------------------------------------------------------------------
# Chain
# ---------------------------------------------------------------------------

class ReceiptChain:
    """Append-only chain of receipt blocks.

    Usage:
        chain = ReceiptChain("/path/to/chain.json")
        chain.append_receipt(some_receipt_dict)
        chain.append_receipt(another_receipt_dict)
        chain.close_block()  # seals current receipts into a block
        assert chain.verify()
    """

    def __init__(self, path: str):
        self.path = Path(path)
        self.blocks: List[ReceiptBlock] = []
        self.pending_receipts: List[Dict[str, Any]] = []
        self.pending_hashes: List[str] = []
        self._load()

    # --- Public API --------------------------------------------------------

    def append_receipt(self, receipt: Dict[str, Any]) -> str:
        """Add a receipt to the pending buffer. Returns its canonical hash."""
        h = canonical_hash(receipt)
        self.pending_receipts.append(receipt)
        self.pending_hashes.append(h)
        return h

    def close_block(self) -> Optional[ReceiptBlock]:
        """Seal pending receipts into a new block. Returns the block or None."""
        if not self.pending_hashes:
            return None

        previous = self.blocks[-1].block_hash if self.blocks else GENESIS_HASH
        block_number = len(self.blocks)

        block = ReceiptBlock(
            block_number=block_number,
            previous_hash=previous,
            receipt_hashes=list(self.pending_hashes),
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        block.seal()

        self.blocks.append(block)
        self.pending_receipts.clear()
        self.pending_hashes.clear()
        self._save()
        return block

    def verify(self) -> bool:
        """Walk the full chain and verify every link."""
        for i, block in enumerate(self.blocks):
            # Block hash integrity
            if not block.verify():
                return False

            # Genesis link
            if i == 0:
                if block.previous_hash != GENESIS_HASH:
                    return False
            else:
                # Chain link: previous_hash must match prior block's hash
                if block.previous_hash != self.blocks[i - 1].block_hash:
                    return False

            # Block number must be sequential
            if block.block_number != i:
                return False

        return True

    def verify_receipt_in_block(
        self, receipt: Dict[str, Any], block_number: int
    ) -> bool:
        """Prove a receipt is in a specific block by recomputing its hash."""
        if block_number < 0 or block_number >= len(self.blocks):
            return False
        h = canonical_hash(receipt)
        return self.blocks[block_number].contains_receipt(h)

    def find_receipt(self, receipt: Dict[str, Any]) -> Optional[int]:
        """Find which block contains a receipt. Returns block_number or None."""
        h = canonical_hash(receipt)
        for block in self.blocks:
            if block.contains_receipt(h):
                return block.block_number
        return None

    @property
    def height(self) -> int:
        """Number of sealed blocks."""
        return len(self.blocks)

    @property
    def total_receipts(self) -> int:
        """Total receipts across all sealed blocks."""
        return sum(len(b.receipt_hashes) for b in self.blocks)

    @property
    def head_hash(self) -> str:
        """Hash of the latest block, or genesis hash if empty."""
        return self.blocks[-1].block_hash if self.blocks else GENESIS_HASH

    def get_block(self, block_number: int) -> Optional[ReceiptBlock]:
        """Get a block by number."""
        if 0 <= block_number < len(self.blocks):
            return self.blocks[block_number]
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Export full chain state."""
        return {
            "chain_version": "v1_linear",
            "height": self.height,
            "total_receipts": self.total_receipts,
            "head_hash": self.head_hash,
            "blocks": [b.to_dict() for b in self.blocks],
        }

    # --- Persistence -------------------------------------------------------

    def _save(self) -> None:
        """Write chain state to disk."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.to_dict(), indent=2), encoding="utf-8"
        )

    def _load(self) -> None:
        """Load chain state from disk if it exists."""
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.blocks = [
                ReceiptBlock.from_dict(b) for b in data.get("blocks", [])
            ]
        except (json.JSONDecodeError, KeyError, TypeError):
            # Corrupted file — start fresh but don't delete the file
            self.blocks = []

    def clear(self) -> None:
        """Reset chain. For testing only."""
        self.blocks.clear()
        self.pending_receipts.clear()
        self.pending_hashes.clear()
        if self.path.exists():
            self.path.unlink()
