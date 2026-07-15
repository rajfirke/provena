from __future__ import annotations

import hashlib
import hmac

GENESIS_HASH = hashlib.sha256(b"provena:genesis").hexdigest()
HASH_ALGORITHM = "sha256"


class ChainHasher:
    def __init__(self, signing_key: bytes | None = None) -> None:
        self._signing_key = signing_key

    @property
    def is_signed(self) -> bool:
        return self._signing_key is not None

    def compute_chain_hash(
        self,
        previous_hash: str,
        content_hash: str,
        source: str,
        timestamp: str,
    ) -> str:
        payload = f"{previous_hash}:{content_hash}:{source}:{timestamp}"
        if self._signing_key is not None:
            return hmac.new(
                self._signing_key,
                payload.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def verify_link(
        self,
        previous_hash: str,
        content_hash: str,
        source: str,
        timestamp: str,
        expected_hash: str,
    ) -> bool:
        computed = self.compute_chain_hash(
            previous_hash, content_hash, source, timestamp
        )
        return hmac.compare_digest(computed, expected_hash)


def content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
