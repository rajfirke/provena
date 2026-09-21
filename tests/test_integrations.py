"""Tests for framework integrations (LangChain, LlamaIndex).

These tests use mock objects to simulate framework types so they run
without langchain-core or llama-index-core installed.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from provena.integrations.langchain import (
    ProvenaCallback,
    _extract_langchain_provenance,
)
from provena.integrations.llamaindex import (
    ProvenaPostprocessor,
    _extract_llamaindex_provenance,
)
from provena.trail import ContextTrail


class MockLangChainDocument:
    def __init__(self, page_content: str, metadata: dict | None = None):
        self.page_content = page_content
        self.metadata = metadata or {}


class MockLlamaIndexNode:
    def __init__(self, text: str, metadata: dict | None = None):
        self.text = text
        self.metadata = metadata or {}


class MockNodeWithScore:
    def __init__(self, node: MockLlamaIndexNode, score: float = 0.9):
        self.node = node
        self.score = score


class MockQueryBundle:
    def __init__(self, query_str: str):
        self.query_str = query_str


class TestExtractLangChainProvenance:
    def test_with_source_metadata(self):
        doc = MockLangChainDocument("text", {"source": "test.pdf", "author": "Alice"})
        prov = _extract_langchain_provenance(doc)
        assert prov is not None
        assert prov.source_url == "test.pdf"
        assert prov.author == "Alice"

    def test_with_source_url_key(self):
        doc = MockLangChainDocument("text", {"source_url": "https://example.com"})
        prov = _extract_langchain_provenance(doc)
        assert prov is not None
        assert prov.source_url == "https://example.com"

    def test_no_metadata(self):
        doc = MockLangChainDocument("text")
        doc.metadata = None
        prov = _extract_langchain_provenance(doc)
        assert prov is None

    def test_empty_metadata(self):
        doc = MockLangChainDocument("text", {})
        prov = _extract_langchain_provenance(doc)
        assert prov is not None
        assert prov.source_url is None
        assert prov.author is None


class TestExtractLlamaIndexProvenance:
    def test_with_source_metadata(self):
        node = MockLlamaIndexNode("text", {"source": "doc.pdf", "author": "Bob"})
        prov = _extract_llamaindex_provenance(node)
        assert prov is not None
        assert prov.source_url == "doc.pdf"
        assert prov.author == "Bob"

    def test_with_file_path(self):
        node = MockLlamaIndexNode("text", {"file_path": "/data/doc.txt"})
        prov = _extract_llamaindex_provenance(node)
        assert prov is not None
        assert prov.source_url == "/data/doc.txt"

    def test_no_metadata(self):
        node = MockLlamaIndexNode("text")
        node.metadata = None
        prov = _extract_llamaindex_provenance(node)
        assert prov is None


_has_langchain = False
try:
    import langchain_core  # noqa: F401

    _has_langchain = True
except ImportError:
    pass


@pytest.mark.skipif(not _has_langchain, reason="langchain-core not installed")
class TestProvenaCallbackLangChain:
    def test_on_retriever_end(self):
        trail = ContextTrail(backend="memory")
        callback = ProvenaCallback(trail=trail)

        docs = [
            MockLangChainDocument("chunk 1", {"source": "file.pdf"}),
            MockLangChainDocument("chunk 2", {"source": "file.pdf"}),
        ]

        callback.on_retriever_end(docs, run_id=uuid4())

        s = trail.summary()
        assert s["total"] == 2
        assert s["sources"]["retriever"] == 2
        trail.close()

    def test_on_tool_end(self):
        trail = ContextTrail(backend="memory")
        callback = ProvenaCallback(trail=trail)

        callback.on_tool_end("tool output data", run_id=uuid4())

        s = trail.summary()
        assert s["total"] == 1
        assert s["sources"]["tool"] == 1
        trail.close()

    def test_on_retriever_end_with_provenance(self):
        trail = ContextTrail(backend="memory")
        callback = ProvenaCallback(trail=trail)

        docs = [MockLangChainDocument("data", {"source": "https://api.com/data"})]
        callback.on_retriever_end(docs, run_id=uuid4())

        records = trail.query()
        assert len(records) == 1
        trail.close()

    def test_empty_documents(self):
        trail = ContextTrail(backend="memory")
        callback = ProvenaCallback(trail=trail)

        callback.on_retriever_end([], run_id=uuid4())

        assert trail.summary()["total"] == 0
        trail.close()


@pytest.mark.skipif(not _has_langchain, reason="langchain-core not installed")
class TestProvenaCallbackIntegration:
    def test_callback_with_verify(self):
        trail = ContextTrail(backend="memory")
        callback = ProvenaCallback(trail=trail)

        for i in range(5):
            docs = [MockLangChainDocument(f"chunk {i}", {"source": f"doc_{i}.pdf"})]
            callback.on_retriever_end(docs, run_id=uuid4())

        verdict = trail.verify_chain()
        assert verdict.intact
        assert verdict.total_records == 5
        trail.close()


class TestProvenaCallbackImportError:
    @pytest.mark.skipif(_has_langchain, reason="langchain IS installed")
    def test_raises_import_error_without_langchain(self):
        with pytest.raises(ImportError, match="langchain-core"):
            ProvenaCallback(trail=ContextTrail(backend="memory"))


_has_llamaindex = False
try:
    import llama_index.core  # noqa: F401

    _has_llamaindex = True
except ImportError:
    pass


@pytest.mark.skipif(not _has_llamaindex, reason="llama-index-core not installed")
class TestProvenaPostprocessorLlamaIndex:
    def test_postprocess_nodes_logs_to_trail(self):
        import json

        trail = ContextTrail(backend="memory")
        postprocessor = ProvenaPostprocessor(trail=trail)

        # 1. Create mock NodeWithScore objects
        node1 = MockLlamaIndexNode(
            "Text chunk 1", {"source": "manual.pdf", "author": "Alice"}
        )
        node2 = MockLlamaIndexNode("Text chunk 2", {"file_path": "/var/data.txt"})

        nodes = [
            MockNodeWithScore(node1, score=0.95),
            MockNodeWithScore(node2, score=0.82),
        ]
        query = MockQueryBundle("how does it work?")

        # 2. Call _postprocess_nodes
        result = postprocessor._postprocess_nodes(nodes, query)

        # 3. Assert pass-through behavior
        assert result is nodes
        assert len(result) == 2

        # 4. Assert trail logs
        s = trail.summary()
        assert s["total"] == 2
        assert s["sources"]["retriever"] == 2

        # 5. Assert provenance and metadata extraction
        records = trail.query()
        assert len(records) == 2

        # Verify Node 1 (has score and query metadata)
        prov1 = json.loads(records[0]["provenance_json"])
        meta1 = json.loads(records[0]["metadata_json"])
        assert prov1["source_url"] == "manual.pdf"
        assert prov1["author"] == "Alice"
        assert meta1["score"] == 0.95
        assert meta1["query"] == "how does it work?"

        # Verify Node 2
        prov2 = json.loads(records[1]["provenance_json"])
        assert prov2["source_url"] == "/var/data.txt"

        trail.close()

    def test_postprocess_red_team_vectors(self):
        import json
        from types import SimpleNamespace

        trail = ContextTrail(backend="memory")
        postprocessor = ProvenaPostprocessor(trail=trail)

        # 1. Malicious Truthiness Object (Simulates a Pandas DataFrame)
        class MaliciousTruthiness:
            def __bool__(self):
                raise ValueError("Truth value is ambiguous")

        # 2. Generator instead of a List
        def node_generator():
            malicious_meta = {
                "created_at": MaliciousTruthiness(),
                "date": "2023-01-01",
                "source": "safe.pdf",
            }
            yield MockNodeWithScore(MockLlamaIndexNode("text", malicious_meta))
            yield MockNodeWithScore(MockLlamaIndexNode("text 2", {}))

        nodes = node_generator()

        # 3. Malformed Query Bundle
        bad_query = SimpleNamespace(wrong_attr="test")

        # Execute (Should not crash!)
        result = postprocessor._postprocess_nodes(nodes, bad_query)

        # Verify Iterator Exhaustion was prevented
        assert isinstance(result, list)
        assert len(result) == 2

        # Verify Truthiness crash was avoided.
        # Since created_at was MaliciousTruthiness, it safely evaluated to None and was omitted.
        records = trail.query()
        prov = json.loads(records[0]["provenance_json"])
        assert prov["source_url"] == "safe.pdf"
        assert prov.get("created_at") is None

        trail.close()


class TestProvenaPostprocessorImportError:
    @pytest.mark.skipif(_has_llamaindex, reason="llama-index IS installed")
    def test_raises_import_error_without_llamaindex(self):
        with pytest.raises(ImportError, match="llama-index-core"):
            ProvenaPostprocessor(trail=ContextTrail(backend="memory"))
