"""SHA-256 hash chain computation and verification."""

from __future__ import annotations

import hashlib
import hmac

GENESIS_HASH = hashlib.sha256(b"provena:genesis").hexdigest()
HASH_ALGORITHM = "sha256"


class ChainHasher:
    """Computes and verifies SHA-256 hash chain links.

    Supports optional HMAC-SHA256 signing when a signing key is provided.
    """

    def __init__(self, signing_key: bytes | None = None) -> None:
        """Initialize the hasher with an optional HMAC signing key."""
        self._signing_key = signing_key

    @property
    def is_signed(self) -> bool:
        """Whether this hasher uses HMAC signing."""
        return self._signing_key is not None

    def compute_chain_hash(
        self,
        previous_hash: str,
        content_hash: str,
        source: str,
        timestamp: str,
    ) -> str:
        """Compute the hash for a chain link.

        Args:
            previous_hash: The chain hash of the preceding record.
            content_hash: SHA-256 hex digest of the content.
            source: Source type string (e.g. ``"retriever"``).
            timestamp: ISO-format timestamp string.

        Returns:
            Hex-encoded SHA-256 or HMAC-SHA256 digest of the link.
        """
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
        """Verify that a chain link matches the expected hash.

        Uses constant-time comparison to prevent timing attacks.

        Args:
            previous_hash: The chain hash of the preceding record.
            content_hash: SHA-256 hex digest of the content.
            source: Source type string.
            timestamp: ISO-format timestamp string.
            expected_hash: The hash value to verify against.

        Returns:
            True if the recomputed hash matches expected_hash.
        """
        computed = self.compute_chain_hash(
            previous_hash, content_hash, source, timestamp
        )
        return hmac.compare_digest(computed, expected_hash)


def content_hash(content: bytes) -> str:
    """Compute the SHA-256 hex digest of raw content bytes."""
    return hashlib.sha256(content).hexdigest()
