from __future__ import annotations

import hashlib

from provena.hasher import GENESIS_HASH, ChainHasher, content_hash


class TestContentHash:
    def test_deterministic(self):
        assert content_hash(b"hello") == content_hash(b"hello")

    def test_different_content(self):
        assert content_hash(b"hello") != content_hash(b"world")

    def test_sha256(self):
        expected = hashlib.sha256(b"test data").hexdigest()
        assert content_hash(b"test data") == expected


class TestGenesisHash:
    def test_is_sha256(self):
        assert len(GENESIS_HASH) == 64
        int(GENESIS_HASH, 16)

    def test_deterministic(self):
        expected = hashlib.sha256(b"provena:genesis").hexdigest()
        assert expected == GENESIS_HASH


class TestChainHasher:
    def test_plain_sha256(self):
        hasher = ChainHasher()
        assert not hasher.is_signed
        h = hasher.compute_chain_hash(
            previous_hash=GENESIS_HASH,
            content_hash="abc123",
            source="retriever",
            timestamp="2026-07-13T00:00:00+00:00",
        )
        assert len(h) == 64

    def test_plain_deterministic(self):
        hasher = ChainHasher()
        h1 = hasher.compute_chain_hash("prev", "content", "src", "ts")
        h2 = hasher.compute_chain_hash("prev", "content", "src", "ts")
        assert h1 == h2

    def test_plain_different_inputs(self):
        hasher = ChainHasher()
        h1 = hasher.compute_chain_hash("prev", "content1", "src", "ts")
        h2 = hasher.compute_chain_hash("prev", "content2", "src", "ts")
        assert h1 != h2

    def test_chain_link_sensitivity(self):
        hasher = ChainHasher()
        h1 = hasher.compute_chain_hash("prev1", "content", "src", "ts")
        h2 = hasher.compute_chain_hash("prev2", "content", "src", "ts")
        assert h1 != h2

    def test_hmac_signed(self):
        hasher = ChainHasher(signing_key=b"secret-key")
        assert hasher.is_signed
        h = hasher.compute_chain_hash("prev", "content", "src", "ts")
        assert len(h) == 64

    def test_hmac_different_from_plain(self):
        plain = ChainHasher()
        signed = ChainHasher(signing_key=b"secret")
        h_plain = plain.compute_chain_hash("prev", "c", "s", "t")
        h_signed = signed.compute_chain_hash("prev", "c", "s", "t")
        assert h_plain != h_signed

    def test_hmac_different_keys(self):
        h1_hasher = ChainHasher(signing_key=b"key1")
        h2_hasher = ChainHasher(signing_key=b"key2")
        h1 = h1_hasher.compute_chain_hash("prev", "c", "s", "t")
        h2 = h2_hasher.compute_chain_hash("prev", "c", "s", "t")
        assert h1 != h2

    def test_verify_link_valid(self):
        hasher = ChainHasher()
        h = hasher.compute_chain_hash("prev", "content", "src", "ts")
        assert hasher.verify_link("prev", "content", "src", "ts", h)

    def test_verify_link_invalid(self):
        hasher = ChainHasher()
        assert not hasher.verify_link("prev", "content", "src", "ts", "wrong")

    def test_verify_link_hmac(self):
        hasher = ChainHasher(signing_key=b"key")
        h = hasher.compute_chain_hash("prev", "content", "src", "ts")
        assert hasher.verify_link("prev", "content", "src", "ts", h)

    def test_full_chain(self):
        hasher = ChainHasher()
        hashes = [GENESIS_HASH]

        for i in range(10):
            h = hasher.compute_chain_hash(
                hashes[-1], f"content_{i}", "retriever", f"ts_{i}"
            )
            hashes.append(h)

        for i in range(10):
            assert hasher.verify_link(
                hashes[i], f"content_{i}", "retriever", f"ts_{i}", hashes[i + 1]
            )

    def test_tamper_detection_in_chain(self):
        hasher = ChainHasher()
        hashes = [GENESIS_HASH]
        for i in range(5):
            h = hasher.compute_chain_hash(
                hashes[-1], f"content_{i}", "retriever", f"ts_{i}"
            )
            hashes.append(h)

        tampered_hash = hasher.compute_chain_hash(
            hashes[1], "TAMPERED", "retriever", "ts_2"
        )
        assert tampered_hash != hashes[3]
