from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import pytest

from app.core.config import settings
from app.schemas.tutor import ChatMessage, DocumentChunk, QueryResponse
from app.services.llm_gateway import LLMGenerationResult
from app.services.rag_service import (
    RAGTrace,
    answer_question,
    answer_question_with_trace,
    call_gemini,
)
from app.services.vector_store import VectorStoreService


class _DeterministicFakeEmbedder:
    """Fast local embedder avoiding network access during unit tests of VectorStoreService."""

    def encode(self, texts, show_progress_bar=False):
        class _VecArray:
            def __init__(self, rows):
                self._rows = rows

            def tolist(self):
                return self._rows

        rows = []
        for t in texts:
            low = t.lower()
            rows.append([
                1.0 if "binary" in low else 0.1,
                1.0 if "merge" in low else 0.1,
                1.0 if "hash" in low else 0.1,
            ])
        return _VecArray(rows)


def test_similarity_search_includes_chunk_id_and_preserves_user_isolation(tmp_path):
    store = VectorStoreService(persist_dir=str(tmp_path / "chroma_eval_test"))
    store._embedder = _DeterministicFakeEmbedder()

    alice_chunk = DocumentChunk(
        id="Algorithms_pdf_p4_c2",
        document_name="Algorithms.pdf",
        page_number=4,
        chunk_index=2,
        text="Binary search runs in O(log n) time on sorted arrays.",
    )
    bob_chunk = DocumentChunk(
        id="Secrets_pdf_p1_c0",
        document_name="Secrets.pdf",
        page_number=1,
        chunk_index=0,
        text="Binary secret belonging strictly to Bob.",
    )

    store.add_document_chunks([alice_chunk], user_id="alice_trace_user", document_id="doc_alice_1")
    store.add_document_chunks([bob_chunk], user_id="bob_trace_user", document_id="doc_bob_1")

    results_alice = store.similarity_search("binary search complexity", user_id="alice_trace_user", top_k=2)
    assert len(results_alice) == 1
    assert results_alice[0]["chunk_id"] == "Algorithms_pdf_p4_c2"
    assert results_alice[0]["document_name"] == "Algorithms.pdf"
    assert results_alice[0]["page_number"] == 4
    assert results_alice[0]["user_id"] == "alice_trace_user"

    # Bob cannot see Alice's chunk and receives only his own chunk_id
    results_bob = store.similarity_search("binary search complexity", user_id="bob_trace_user", top_k=2)
    assert len(results_bob) == 1
    assert results_bob[0]["chunk_id"] == "Secrets_pdf_p1_c0"
    assert results_bob[0]["user_id"] == "bob_trace_user"


class _StubStore:
    def __init__(self, chunks):
        self._chunks = chunks

    def similarity_search(self, query, user_id=None, top_k=4, document_filter=None):
        return self._chunks[:top_k]


def test_trace_captures_standalone_query_and_retrieved_chunks():
    chunks = [
        {
            "chunk_id": "DS_p2_c1",
            "document_name": "DS.pdf",
            "page_number": 2,
            "chunk_index": 1,
            "text": "A stack follows Last-In-First-Out ordering.",
            "similarity": 0.91,
        }
    ]
    store = _StubStore(chunks)
    history = [
        ChatMessage(role="user", content="Tell me about stacks."),
        ChatMessage(role="assistant", content="Stacks store items."),
    ]

    def mock_rewrite(prompt: str) -> str:
        return "What ordering rule does a stack use?"

    def mock_llm(prompt: str) -> str:
        return "A stack uses LIFO ordering [Document: DS.pdf, Page: 2]."

    response, trace = answer_question_with_trace(
        question="What ordering does it use?",
        user_id="trace_user_1",
        vector_store=store,  # type: ignore
        history=history,
        rewrite_callable=mock_rewrite,
        llm_callable=mock_llm,
    )

    assert isinstance(response, QueryResponse)
    assert isinstance(trace, RAGTrace)
    assert trace.standalone_query == "What ordering rule does a stack use?"
    assert len(trace.retrieved_chunks) == 1
    assert trace.retrieved_chunks[0]["chunk_id"] == "DS_p2_c1"
    assert trace.max_similarity == 0.91
    assert trace.threshold_triggered is False
    assert trace.clarification_triggered is False
    # Telemetry via custom callables cannot be fabricated and remains None
    assert trace.rewriter_telemetry is None
    assert trace.generation_telemetry is None


def test_trace_captures_threshold_triggered_decision(monkeypatch):
    monkeypatch.setattr(settings, "SIMILARITY_THRESHOLD", 0.5)
    low_chunks = [
        {
            "chunk_id": "Notes_p1_c0",
            "document_name": "Notes.pdf",
            "page_number": 1,
            "chunk_index": 0,
            "text": "Unrelated introductory text.",
            "similarity": 0.22,
        }
    ]
    store = _StubStore(low_chunks)

    response, trace = answer_question_with_trace(
        question="Explain quantum error correction",
        user_id="trace_user_2",
        vector_store=store,  # type: ignore
    )

    assert response.insufficient_context is True
    assert response.citations == []
    assert trace.threshold_triggered is True
    assert trace.max_similarity == 0.22
    assert len(trace.retrieved_chunks) == 1
    assert trace.generation_telemetry is None


def test_trace_records_clarification_path():
    store = _StubStore([])
    history = [
        ChatMessage(role="user", content="We covered sorting."),
        ChatMessage(role="assistant", content="Yes, mergesort and quicksort."),
    ]

    response, trace = answer_question_with_trace(
        question="Show me that",
        user_id="trace_user_3",
        vector_store=store,  # type: ignore
        history=history,
        rewrite_callable=lambda p: "CLARIFY: Did you mean mergesort or quicksort?",
    )

    assert response.insufficient_context is False
    assert "mergesort or quicksort" in response.answer
    assert trace.clarification_triggered is True
    assert trace.standalone_query.startswith("CLARIFY:")
    assert trace.retrieved_chunks == []
    assert trace.threshold_triggered is False
    assert trace.generation_telemetry is None


def test_trace_captures_gateway_telemetry_for_rewriter_and_generation(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test_key_123")
    monkeypatch.setattr(settings, "OBSERVABILITY_ENABLED", False)

    chunks = [
        {
            "chunk_id": "Graphs_p8_c0",
            "document_name": "Graphs.pdf",
            "page_number": 8,
            "chunk_index": 0,
            "text": "BFS explores vertices level by level using a queue.",
            "similarity": 0.93,
        }
    ]
    store = _StubStore(chunks)
    history = [
        ChatMessage(role="user", content="Explain BFS."),
        ChatMessage(role="assistant", content="BFS traverses graphs."),
    ]

    rewrite_gw = LLMGenerationResult(
        text="Which data structure does BFS use?",
        model_used="gemini-3.5-flash-lite",
        model_version="gemini-3.5-flash-lite-001",
        prompt_tokens=40,
        output_tokens=10,
        total_tokens=50,
        thoughts_tokens=None,
        latency_ms=11.5,
        retries=0,
        fallback_used=False,
    )
    gen_gw = LLMGenerationResult(
        text="BFS uses a queue [Document: Graphs.pdf, Page: 8].",
        model_used="gemini-2.5-flash",
        model_version="gemini-2.5-flash-002",
        prompt_tokens=150,
        output_tokens=22,
        total_tokens=180,
        thoughts_tokens=8,
        latency_ms=42.0,
        retries=0,
        fallback_used=False,
    )

    with patch("app.services.rag_service.generate_text", side_effect=[rewrite_gw, gen_gw]) as mock_gen:
        response, trace = answer_question_with_trace(
            question="What structure does it use?",
            user_id="trace_user_4",
            vector_store=store,  # type: ignore
            history=history,
            model="gemini-2.5-flash",
        )

    assert mock_gen.call_count == 2
    assert response.model_used == "gemini-2.5-flash"
    assert len(response.citations) == 1
    assert trace.rewriter_telemetry == rewrite_gw
    assert trace.generation_telemetry == gen_gw
    assert trace.generation_telemetry.prompt_tokens == 150
    assert trace.generation_telemetry.output_tokens == 22
    assert trace.generation_telemetry.thoughts_tokens == 8


def test_answer_question_preserves_query_response_return_and_patchable_call_gemini(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test_key_123")
    chunks = [
        {
            "chunk_id": "Trees_p3_c0",
            "document_name": "Trees.pdf",
            "page_number": 3,
            "chunk_index": 0,
            "text": "AVL trees keep balance factors in {-1, 0, 1}.",
            "similarity": 0.90,
        }
    ]
    store = _StubStore(chunks)

    with patch(
        "app.services.rag_service.call_gemini",
        return_value="AVL trees maintain balance factor in {-1, 0, 1} [Document: Trees.pdf, Page: 3].",
    ) as mock_call:
        res = answer_question(
            question="What is the AVL balance factor invariant?",
            user_id="compat_user",
            vector_store=store,  # type: ignore
        )

    mock_call.assert_called_once()
    assert type(res) is QueryResponse
    assert not isinstance(res, tuple)
    assert res.citations[0].page_number == 3


def test_call_gemini_client_and_sleep_fn_injection_preserved(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test_key_123")
    monkeypatch.setattr(settings, "OBSERVABILITY_ENABLED", False)

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = [
        Exception("429 RESOURCE_EXHAUSTED: transient"),
        SimpleNamespace(text="Injected success", model_version="gemini-test", usage_metadata=None),
    ]
    mock_sleep = MagicMock()

    text = call_gemini(
        prompt="Hi",
        model="gemini-3.5-flash-lite",
        client=mock_client,
        sleep_fn=mock_sleep,
    )

    assert text == "Injected success"
    assert mock_client.models.generate_content.call_count == 2
    mock_sleep.assert_called_once()

